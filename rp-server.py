#!/usr/bin/env python

import dbus, gobject
from dbus.mainloop.glib import DBusGMainLoop
from dbus.mainloop.glib import threads_init as dbus_threads_init

import sys
import time
import socket
import threading

import purple_pb2

if(len(sys.argv) == 2):
    __password__ = sys.argv[1]
else:
    print "[SERVER] Usage: rp-server.py password"
    exit(1)

__DEBUG__ = True

dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
bus = dbus.SessionBus()
obj = bus.get_object("im.pidgin.purple.PurpleService", "/im/pidgin/purple/PurpleObject")
purple = dbus.Interface(obj, "im.pidgin.purple.PurpleInterface")

_STATUS = ("unknown", "offline", "available", "unavailable", "invisible", "away", "extended_away", "mobile", "tune")
_ONLINE = ("offline", "online")

## Classes ##

class Conversation:
    def __init__(self, ID, name, account):
        self.ID = ID
        self.name = name
        self.accountID = account
        self.ImID = purple.PurpleConvIm(ID)
        
        self.messages = []
        self._refresh_history()
        return

    def get_protobuf(self):
        pb = purple_pb2.Conversation()
        pb.conversationID = self.ID
        pb.accountID = self.accountID
        pb.name = self.name
        for msg in self.messages:
            message = pb.messages.add()
            message.conversation = self.ID
            message.sender = msg['sender']
            message.message = msg['message']
            message.timestamp = msg['timestamp']
        return pb    
        
    def _refresh_history(self):
        msghistory = purple.PurpleConversationGetMessageHistory(self.ID)
        msghistory.reverse() # By default newest is first
        for msg in msghistory:
            msg_text = purple.PurpleConversationMessageGetMessage(msg)
            msg_timestamp = purple.PurpleConversationMessageGetTimestamp(msg)
            msg_sender = purple.PurpleConversationMessageGetSender(msg)
            self.messages.append({"message": msg_text, "sender": msg_sender, "timestamp": msg_timestamp})
        return

    def new_message(self, sender, message):
        self.messages.append({"message": message, "sender": sender, "timestamp": int(time.time())})
        return

    def get_name(self):
        return self.name

    def get_accountID(self):
        return self.accountID

    def get_imID(self):
        return self.ImID

    def get_messages(self):
        return self.messages
    pass

## Everything else ##

def protosend(sock, tosend):
    # Send message in Remote Purple-protocol ("<payload length>;<payload>")
    tosend = str(len(tosend))+";"+tosend
    sock.sendall(tosend)

def build_status():
    global accounts # Accounts contain everything else except convs.
    global convs
    status = purple_pb2.Status()
    for accountID in accounts:
        account = status.accounts.add()
        account.accountID = accountID
        account.protocol = accounts[accountID]['protocol']
        account.ownpresence.buddyID = accountID
        account.ownpresence.alias = accounts[accountID]['name']
        account.ownpresence.state = accounts[accountID]['status']
        account.ownpresence.extended_status = accounts[accountID]['statusmsg']
        for buddyID in accounts[accountID]['buddies']:
            buddy_d = accounts[accountID]['buddies'][buddyID]
            buddy = account.buddylist.add()
            buddy.buddyID = buddyID
            buddy.alias = buddy_d['alias']
            buddy.state = _ONLINE[buddy_d['online']] # Only offline/online for now
            buddy.extended_status = buddy_d['extstatus']
    for conv in convs:
        conversation = status.conversations.add()
        conversation.MergeFrom(convs[conv].get_protobuf())
    return status

def _receive(sock):
    # Protocol: <payload length>;<payload>
    buf = sock.recv(10)
    try:
        payload_len = int(buf[:buf.find(";")])
    except:
        return ""
    payload = buf[buf.find(";")+1:]
    while(len(payload) < payload_len):
        print str(len(payload))+" / "+str(payload_len)
        buf = sock.recv(payload_len - len(payload)) # We've already received a part of the payload. Try to figure out how much
        payload = payload+buf
    print str(len(payload))+" / "+str(payload_len)
    return payload

def _parse_command(command, clientID):
    global clients
    global accounts
    global convs
    global purple

    if(command.find(";") == -1):
        rectype = command
        payload = None
    else:
        rectype = command[:command.find(";")]
        payload = command[command.find(";")+1:]

    print "[SERVER] Received: "+rectype
    if(rectype == "IM"):
        im = purple_pb2.IM()
        im.ParseFromString(payload)
        if(__DEBUG__):
            print im
        im_id = convs[im.conversation].get_imID()
        purple.PurpleConvImSend(im_id, im.message)
    elif(rectype == "NewConversation"):
        conv = purple_pb2.Conversation()
        conv.ParseFromString(payload)
        if(__DEBUG__):
            print conv
        accID = conv.accountID
        name = accounts[accID]['buddies'][conv.conversationID]['name']
        purple.PurpleConversationNew(1, accID, name)
    elif(rectype == "DeleteConversation"):
        conv = purple_pb2.Conversation()
        conv.ParseFromString(payload)
        if(__DEBUG__):
            print conv
        convID = conv.conversationID
        purple.PurpleConversationDestroy(convID)
        # Deleting conversation happens in conv-deletion-signal handler
    elif(rectype == "Ping"):
        protosend(clients[clientID]['client'], "Pong")
    else:
        protosend(clients[clientID]['client'], "Unknown command")

def _listen(ID):
    global clients
    while True:
        received = _receive(clients[ID]['client'])
        if received != "":
            if(clients[ID]['authenticated'] == False):
                if(received.strip() == __password__):
                    print "[SERVER] Authenticated"
                    clients[ID]['client'].sendall("Authdone") # Client waits for 8 character-string to determine authfail/success
                    status = build_status()
                    status = status.SerializeToString()
                    protosend(clients[ID]['client'], status)
                    clients[ID]['authenticated'] = True 
                else:
                    print "[SERVER] Authentication failed"
                    clients[ID]['client'].sendall("Authfail")
                    clients[ID]['client'].close()
                    clients[ID]['client'] = None
                    clients[ID]['address'] = None
                    clients[ID]['authenticated'] = False
                    clients[ID]['recycled'] = True
                    break
            
            else:
                _parse_command(received, ID)
        else:
            print str(ID)+": Remote host has closed connection"
            clients[ID]['client'].close()
            clients[ID]['client'] = None
            clients[ID]['address'] = None
            clients[ID]['authenticated'] = False
            clients[ID]['recycled'] = True
            break
    if(clients[ID]['client'] == None):
        _accept_connection(ID)

def _accept_connection(ID):
    global clients
    (clients[ID]['client'], clients[ID]['address']) = serversocket.accept()
    print str(ID)+": New client: "+str(clients[ID]['address'][0])+":"+str(clients[ID]['address'][1])
    if(clients[ID]['recycled'] == False):
        clients.append({"thread": threading.Thread(target = _accept_connection, args=(ID+1,)), "client": None, "authenticated": False, "recycled": False})
        clients[-1]['thread'].start()
    _listen(ID)

def msg_received(account, sender, message, conv, flags):
    if(conv == 0): # Unknown conversation. Meh
        return
    global clients
    global convs
    print "[SERVER] IM GET: "+sender+": "+message
    
    IM = purple_pb2.IM()
    IM.conversation = conv
    IM.sender = sender
    IM.message = message
    IM.timestamp = int(time.time())
    IM_ser = IM.SerializeToString()
    
    if conv in convs:
       convs[conv].new_message(sender, message)
    else:
       convs[conv] = Conversation(conv, name, account)
       convs[conv].new_message(sender, message)
    for client in clients:
        if((client['client'] != None) and (client['authenticated'] == True)):
            try:
                protosend(client['client'], "IM;"+IM_ser)
            except:
                client['client'] = None
                client['address'] = None
                client['authenticated'] = False
    return

def im_sent(account, receiver, message):
    global clients
    global convs
    if(__DEBUG__):
        print "[SERVER] IM SENT -> "+receiver+": "+message
    sender = purple.PurpleAccountGetUsername(account)
    # Figure out conversationID
    conv = 0
    for convID in convs:
        if convs[convID].get_name() == receiver:
            conv = convID
            break
  
    IM = purple_pb2.IM()
    IM.conversation = conv
    IM.sender = sender
    IM.message = message
    IM.timestamp = int(time.time())
    IM.sent = True
    IM_ser = IM.SerializeToString()
    
    if conv in convs:
       convs[conv].new_message(sender, message)
    else:
       convs[conv] = Conversation(conv, purple.PurpleConversationGetName(conv), purple.PurpleConversationGetAccount(conv))
       convs[conv].new_message(sender, message)
    for client in clients:
        if((client['client'] != None) and (client['authenticated'] == True)):
            try:
                protosend(client['client'], "IM;"+IM_ser)
            except:
                client['client'] = None
                client['address'] = None
                client['authenticated'] = False
    return

def new_conversation(conv):
    global convs
    global clients
    global purple
    if conv not in convs:
        convs[conv] = Conversation(conv, purple.PurpleConversationGetName(conv), purple.PurpleConversationGetAccount(conv))
    conversation = convs[conv].get_protobuf()
    
    for client in clients:
        if((client['client'] != None) and (client['authenticated'] == True)):
            try:
                protosend(client['client'], "NewConversation;"+conversation.SerializeToString())
            except:
                client['client'] = None
                client['address'] = None
                client['authenticated'] = False
    return

def delete_conversation(conv):
    global convs
    global clients
    conversation = purple_pb2.Conversation()
    conversation.conversationID = conv
    conversation.accountID = convs[conv].get_accountID()
    conversation.name = convs[conv].get_name()
    del convs[conv] # Remove conversation
    for client in clients:
        if((client['client'] != None) and (client['authenticated'] == True)):
            try:
                protosend(client['client'], "DeleteConversation;"+conversation.SerializeToString())
            except:
                client['client'] = None
                client['address'] = None
                client['authenticated'] = False
    return


def chat_sent(account, message, chatid):
    return

def buddy_signed_on(buddyID):
    accountID = purple.PurpleBuddyGetAccount(buddyID)
    accounts[accountID]['buddies'][buddyID]["online"] = 1

    presence = purple_pb2.Presence()
    presence.buddyID = buddyID 
    presence.state = "online"
    
    for client in clients:
        if((client['client'] != None) and (client['authenticated'] == True)):
            try:
                protosend(client['client'], "BuddyState;"+presence.SerializeToString())
            except:
                client['client'] = None
                client['address'] = None
                client['authenticated'] = False
    
    return

def buddy_signed_off(buddyID):
    accountID = purple.PurpleBuddyGetAccount(buddyID)
    accounts[accountID]['buddies'][buddyID]["online"] = 0

    presence = purple_pb2.Presence()
    presence.buddyID = buddyID 
    presence.state = "offline"
    
    for client in clients:
        if((client['client'] != None) and (client['authenticated'] == True)):
            try:
                protosend(client['client'], "BuddyState;"+presence.SerializeToString())
            except:
                client['client'] = None
                client['address'] = None
                client['authenticated'] = False

    return


def get_buddyID(screenname):
    for accountID, account in accounts.items():
        buddies_raw = purple.PurpleFindBuddies(accountID, screenname)
        if(buddies_raw.length >0):
            return buddies_raw[0]
    return None

bus.add_signal_receiver(msg_received,
                        dbus_interface="im.pidgin.purple.PurpleInterface",
                        signal_name="ReceivedImMsg")
bus.add_signal_receiver(msg_received,
                        dbus_interface="im.pidgin.purple.PurpleInterface",
                        signal_name="ReceivedChatMsg")
bus.add_signal_receiver(im_sent,
                        dbus_interface="im.pidgin.purple.PurpleInterface",
                        signal_name="SentImMsg")
bus.add_signal_receiver(chat_sent,
                        dbus_interface="im.pidgin.purple.PurpleInterface",
                        signal_name="SentChatMsg")

bus.add_signal_receiver(new_conversation,
                        dbus_interface="im.pidgin.purple.PurpleInterface",
                        signal_name="ConversationCreated")
bus.add_signal_receiver(delete_conversation,
                        dbus_interface="im.pidgin.purple.PurpleInterface",
                        signal_name="DeletingConversation")

bus.add_signal_receiver(buddy_signed_on,
                        dbus_interface="im.pidgin.purple.PurpleInterface",
                        signal_name="BuddySignedOn")
bus.add_signal_receiver(buddy_signed_off,
                        dbus_interface="im.pidgin.purple.PurpleInterface",
                        signal_name="BuddySignedOff")

convs_raw = purple.PurpleGetIms()
convs = dict()
for conv in convs_raw:
    convs[conv] = Conversation(conv, purple.PurpleConversationGetName(conv), purple.PurpleConversationGetAccount(conv))

accounts_raw = purple.PurpleAccountsGetAllActive()
accounts = dict()
for accountID in accounts_raw:
    account = {"username": purple.PurpleAccountGetUsername(accountID),
               "name": purple.PurpleAccountGetNameForDisplay(accountID),
               "protocol": purple.PurpleAccountGetProtocolName(accountID),
               "savedstatus": purple.PurpleSavedstatusGetCurrent(),
               "status": _STATUS[purple.PurpleSavedstatusGetType(purple.PurpleSavedstatusGetCurrent())],
               "buddies": dict()}
    account['statusmsg'] = purple.PurpleSavedstatusGetMessage(account['savedstatus'])
    buddies_raw = purple.PurpleFindBuddies(accountID, "")
    for buddyID in buddies_raw:
        buddy = {"alias": purple.PurpleBuddyGetAlias(buddyID), 
                 "name": purple.PurpleBuddyGetName(buddyID), 
                 "online": purple.PurpleBuddyIsOnline(buddyID),
                 "extstatus":  purple.PurpleStatusGetAttrString(purple.PurplePresenceGetActiveStatus(purple.PurpleBuddyGetPresence(buddyID)), "message")}
        account['buddies'][buddyID] = buddy
    accounts[accountID] = account

clients = list()
serversocket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
serversocket.bind(('0.0.0.0', 7890))
serversocket.listen(5)
clients.append({"thread": threading.Thread(target = _accept_connection, args=(0,)), "client": None, "authenticated": False, "recycled": False})
clients[0]['thread'].start()
print "[SERVER] Accepting connections"

loop = gobject.MainLoop()
gobject.threads_init()
dbus_threads_init()
loop.run()
