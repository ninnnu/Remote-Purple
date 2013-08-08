import socket

import purple_pb2

class AuthError(Exception):
    pass

class IM:
    def __init__(self, ts, sender, message, sent = False):
        self.timestamp = ts
        self.sender = sender
        self.message = message
        self.sent = sent

class Conversation:
    def __init__(self, convID, accID, name):
        self.convID = convID
        self.accountID = accID
        self.name = name
        self.messages = list()
        self.buddyID = None

    def add_im(self, pb_im):
        self.messages.append(IM(pb_im.timestamp, pb_im.sender, pb_im.message, pb_im.sent))

    def get_convID(self):
        return self.convID

class Buddy:
    def __init__(self, buddyID, accID, address, alias, state):
        self.buddyID = buddyID
        self.accountID = accID
        self.address = address
        self.alias = alias
        self.state = state
        self.conversationID = None

    def set_conversationID(self, newid):
        self.conversationID = newid

    def get_alias(self):
        return self.alias

    def get_address(self):
        return self.address

    def get_conversationID(self):
        return self.conversationID

class Account:
    def __init__(self, accID, address, alias, state):
        self.accountID = accID
        self.address = address
        self.alias = alias
        self.state = state
        self.conversations = dict()
        self.buddies = dict()

    def add_buddy(self, pb_buddy):
        self.buddies[pb_buddy.buddyID] = Buddy(pb_buddy.buddyID, self.accountID, pb_buddy.name, pb_buddy.alias, pb_buddy.state)

    def add_conversation(self, conversation):
        self.conversations[conversation.convID] = conversation

    def buddyname2id(self, bname):
        for bid in self.buddies:
            if(self.buddies[bid].address == bname):
                return bid
        return None

    def get_buddy(self, buddyID):
        return self.buddies[buddyID]

class RPClient:
    def __init__(self, host, port, password):
        self.status = purple_pb2.Status()
        self.accounts = dict()
        self.conversations = dict()
        self.buddies = dict()
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
        
        for account in self.status.accounts:
            self.accounts[account.accountID] = Account(account.accountID, account.ownpresence.name, account.ownpresence.alias, account.ownpresence.state)
            for buddy in account.buddylist:
                self.accounts[account.accountID].add_buddy(buddy)
                self.buddies[buddy.buddyID] = self.accounts[account.accountID].get_buddy(buddy.buddyID)
        for pb_conv in self.status.conversations:
            self.conversations[pb_conv.conversationID] = Conversation(pb_conv.conversationID, pb_conv.accountID, pb_conv.name)
            for im in pb_conv.messages:
                self.conversations[pb_conv.conversationID].add_im(im)
            self.accounts[pb_conv.accountID].add_conversation(self.conversations[pb_conv.conversationID])          

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
    
        if(rectype == "Bye"):
            self.s = None
            return ("Disconnected", None)

    def get_accounts(self):
        return self.status.accounts
    
    def get_conversations(self):
        return self.conversations
    
    def get_conversation(self, convid):
        return self.conversation[convid]

    def get_buddyalias(self, buddyid):
        return self.buddies[buddyid].alias

    def get_buddyname(self, buddyid):
        return self.buddies[buddyid].name

    def buddy_name2alias(self, name):
        for buddyID in self.buddies:
            if(self.buddies[buddyID].get_address() == name):
                return self.buddies[buddyID].get_alias()

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

