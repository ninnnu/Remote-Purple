import socket

import purple_pb2

class AuthError(Exception):
    pass

class RPClient:
    def __init__(self, host, port, password):
        self.orphans = list() # Orphan received messages. I.e received messages although there's no conversation.
        self.status = purple_pb2.Status()
        self.s = socket.socket()
        self.s.settimeout(3*60) # 3 minutes
        try:
            self.s.connect((host, port))
        except:
            raise socket.error("Connection failed")
        self.protosend(password)
        response = self._receive()
        if(response != "Authdone"):
            print "[RPClient] Authentication failed"
            self.s.close()
            self.s = None
            raise AuthError("Incorrect password")
        else:
            print "[RPClient] Password accepted"
        self.status.ParseFromString(self._receive())
        
        self.buddies = dict()
        for account in self.status.accounts:
            for buddy in account.buddylist:
                self.buddies[buddy.buddyID] = buddy

    def _receive(self):
        # Protocol: <payload length>;<payload>
        try:
            buf = self.s.recv(10)
        except socket.timeout:
            if(self.protosend("Ping")):
                return self._receive()
            else:
                print "[RPClient] Connection to server lost"
                return None
        payload_len = int(buf[:buf.find(";")])
        payload = buf[buf.find(";")+1:]
        while(len(payload) < payload_len):
            buf = self.s.recv(payload_len - len(payload)) # We've already received a part of the payload. Try to figure out how much
            payload = payload+buf
        return payload

    def listen_update(self):
        # TODO: How to signal changes to UI?
        received = self._receive() # Beef = <Payload type>;<Payload>
        if(received == None):
            return None
        if(received.find(";") == -1):
            rectype = received
            payload = None
        else:
            rectype = received[:received.find(";")]
            payload = received[received.find(";")+1:]

        print rectype
        if(rectype == "IM"):
            temp = purple_pb2.IM()
            temp.ParseFromString(payload)
            convID = 0
            i = 0
            for conv in self.status.conversations: # Find right conversation
                if conv.conversationID == temp.conversation:
                    new_im = self.status.conversations[i].messages.add() # And add message to log
                    new_im.ParseFromString(payload)
                    convID = self.status.conversations[i].conversationID
                    return ("IM", convID, new_im) # Update type: IM, ID of updated conversation, the new line
                else:
                    i = i+1
            # Conversation not found. Either we've missed NewConversation for whatever reason or it comes later.
            return ("Empty", None) # Return something meaningless
        
        if(rectype == "NewConversation"): # New conversation
            conversation = self.status.conversations.add() 
            conversation.ParseFromString(payload)
            return ("NewConversation", conversation)

        if(rectype == "DeleteConversation"): # Deleting conversation
            conversation = purple_pb2.Conversation()
            conversation.ParseFromString(payload)
            return ("DeleteConversation", conversation)

        if(rectype == "BuddyState"): # Buddy state has changed
            presence = purple_pb2.Presence()
            presence.ParseFromString(payload)
            self.buddies[presence.buddyID] = presence
            return ("BuddyState", presence)
        
        if(rectype == "Pong"): # Connection is still up.
            return ("Empty", None) # UI doesn't have to really know what's going on

    def get_accounts(self):
        return self.status.accounts
    
    def get_conversations(self):
        return self.status.conversations

    def get_buddyname(self, buddyid):
        return self.buddies[buddyid].alias

    def protosend(self, payload, payload_type=None):
        # Send message in Remote Purple-protocol ("<payload length>;<payload>")
        if(payload_type == None):
            tosend = str(len(payload))+";"+payload
        else:
            payload = payload.SerializeToString()
            tosend = payload_type+";"+payload
            tosend = str(len(tosend))+";"+tosend
        try:
            self.s.sendall(tosend)
        except:
            self.s = None
            return False
        return True

