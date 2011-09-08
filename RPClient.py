import socket

import purple_pb2

class AuthError(Exception):
    pass

class RPClient:
    def __init__(self, host, port, password):
        self.orphans = list() # Orphan received messages. I.e received messages although there's no conversation.
        self.status = purple_pb2.Status()
        self.s = socket.socket()
        try:
            self.s.connect((host, port))
        except:
            raise socket.error("Connection failed")
        self.protosend(password)
        response = self.s.recv(8)
        if(response == "Authfail"):
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
        buf = self.s.recv(10)
        payload_len = int(buf[:buf.find(";")])
        payload = buf[buf.find(";")+1:]
        while(len(payload) < payload_len):
            buf = self.s.recv(payload_len - len(payload)) # We've already received a part of the payload. Try to figure out how much
            payload = payload+buf
        return payload

    def listen_update(self):
        # TODO: How to signal changes to UI?
        received = self._receive() # Beef = <Payload type>;<Payload>
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
            self.orphans.append(temp)
            print "[RPClient] Orphanising: "+temp.message
            # Conversation not found. Either we've missed NewConversation for whatever reason or it comes later.
            return ("Empty", None) # Return something meaningless
        
        if(rectype == "NewConversation"): # New conversation
            conversation = self.status.conversations.add() 
            conversation.ParseFromString(payload)
            for orphanIM in self.orphans:
                if orphanIM.conversationID == conversation.conversationID:
                    newIM = conversation.messages.add()
                    newIM.MergeFrom(orphanIM)
                    print "[RPClient] Unorphanising: "+orphanIM.message
                    self.orphans.remove(orphanIM)
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
        

    def get_accounts(self):
        return self.status.accounts
    
    def get_conversations(self):
        return self.status.conversations

    def get_buddyname(self, buddyid):
        return self.buddies[buddyid].alias

    def protosend(self, payload, payload_type=None):
        # Send message in Remote Purple-protocol ("<payload length>;<payload>")
        if(payload_type == None):
            tosend = tosend = str(len(payload))+";"+payload
        else:
            payload = payload.SerializeToString()
            tosend = payload_type+";"+payload
            tosend = str(len(tosend))+";"+tosend
        self.s.sendall(tosend)

