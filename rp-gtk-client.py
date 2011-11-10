import gobject
import pygtk
pygtk.require('2.0')
import gtk

import pynotify
import time
import sys

import purple_pb2
import threading
import RPClient

if(len(sys.argv) == 3):
    password = sys.argv[2]
    host = sys.argv[1]
else:
    print "Usage: rp-gtk-glient.py <host> <password>"
    exit(1)

port = 7890

_COLORS = {u"online": "#55FF55", u"away": "#FFFF00", u"offline": "#FF5555"}

try:
    rp = RPClient.RPClient(host, port, password)
except:
    print "Connecting to server failed"
    exit(1)

class Conversations:
    def key_event(self, widget, event, convID):
        keyname = gtk.gdk.keyval_name(event.keyval)
        if(keyname == "Return"):
            if((event.state == gtk.gdk.CONTROL_MASK) or # Ctrl+enter -> add enter
               (event.state == gtk.gdk.SHIFT_MASK)): # Shift+enter -> add enter
                return False
            # Send message
            beg_iter = self.conversations[convID][2].get_start_iter()
            end_iter = self.conversations[convID][2].get_end_iter()
            im = purple_pb2.IM()
            im.conversation = convID
            im.message = self.conversations[convID][2].get_text(beg_iter, end_iter)
            if(len(im.message) > 0):
                print str(convID)+" - Sending:"
                print im.message
                rp.protosend(im, "IM")
                self.conversations[convID][2].delete(beg_iter, end_iter)
            return True
        return False

    def delete_event(self, widget, event, data=None):
        return False

    def __init__(self):
        self.conversations = dict()
        self.window = gtk.Window(gtk.WINDOW_TOPLEVEL)
        self.window.set_title("Remote Purple - Conversations")
        self.window.set_size_request(600,400)
        self.window.connect("delete_event", self.delete_event)
        self.notebook = gtk.Notebook()
        self.notebook.set_tab_pos(gtk.POS_TOP)
        self.notebook.connect("switch-page", self.switch_event)

        self.toolbar = gtk.Toolbar()
        self.close = gtk.ToolButton(gtk.STOCK_CLOSE)
        self.close.connect("clicked", self.close_conversation)
        self.toolbar.insert(self.close, 0)

        vbox = gtk.VBox(False, 2)
        vbox.pack_start(self.toolbar, False, False, 0)
        self.close.show()
        self.toolbar.show()

        for conv in rp.get_conversations():
            vpaned = gtk.VPaned()
            label = gtk.Label(conv.name)
            label.show()
            convlog = gtk.TextView()
            convlog.set_wrap_mode(gtk.WRAP_WORD)
            convlog.set_cursor_visible(False)
            convlog.set_editable(False)
            imbuffer = convlog.get_buffer()
            for im in conv.messages:
                while((im.message.find("<FONT") == 0) and (im.message[-1] == ">")):
                    im.message = im.message[im.message.find('>')+1:im.message.rfind('<')] # Strip <FONT>-crap
                timestamp = time.ctime(im.timestamp)
                line = "("+timestamp+") "+im.sender+": "+im.message+"\n"
                imbuffer.insert_at_cursor(line)
            convlog.show()
            end_iter = imbuffer.get_end_iter()
            convlog.scroll_to_mark(imbuffer.get_insert(), 0)
            scrollwin = gtk.ScrolledWindow()
            scrollwin.set_policy(gtk.POLICY_AUTOMATIC, gtk.POLICY_AUTOMATIC)
            scrollwin.add(convlog)
            scrollwin.show()
            textentry = gtk.TextView()
            textentry.set_wrap_mode(gtk.WRAP_WORD)
            textentry.connect("key_press_event", self.key_event, conv.conversationID)
            textentry.show()
            self.conversations[conv.conversationID] = [conv, convlog.get_buffer(), textentry.get_buffer()]
            vpaned.add1(scrollwin)
            vpaned.add2(textentry)
            vpaned.set_position(300)
            vpaned.show()
            self.notebook.append_page(vpaned, label)
        self.notebook.show()
        vbox.pack_end(self.notebook, True, True, 0)
        vbox.show()
        self.window.add(vbox)
        self.window.show()
    def new_line(self, convID, im):
        end_iter = self.conversations[convID][1].get_end_iter()
        beg_iter = self.conversations[convID][1].get_start_iter()
        timestamp = time.ctime(im.timestamp)
        line = "("+timestamp+") "+im.sender+": "+im.message+"\n"
        self.conversations[convID][1].insert(end_iter, line)
        # Scroll to down
        convname = self.conversations[convID][0].name
        i = 0
        page_id = self.convID_to_page(convID)
        vpaned = self.notebook.get_nth_page(page_id)
        scrollwin = vpaned.get_child1()
        convlog = scrollwin.get_child()
        convlog.scroll_to_mark(self.conversations[convID][1].get_insert(),0)
        if(self.notebook.get_current_page() != page_id):
            self.hilight_conv(convID, "red")
        return
    
    def new_conversation(self, conv):
        vpaned = gtk.VPaned()
        label = gtk.Label(conv.name)
        label.set_markup("<span foreground=\"red\">"+conv.name+"</span>")
        label.show()
        convlog = gtk.TextView()
        convlog.set_wrap_mode(gtk.WRAP_WORD)
        convlog.set_cursor_visible(False)
        convlog.set_editable(False)
        imbuffer = convlog.get_buffer()
        for im in conv.messages:
            while((im.message.find("<FONT") == 0) and (im.message[-1] == ">")):
                im.message = im.message[im.message.find('>')+1:im.message.rfind('<')] # Strip <FONT>-crap
            timestamp = time.ctime(im.timestamp)
            line = "("+timestamp+") "+im.sender+": "+im.message+"\n"
            imbuffer.insert_at_cursor(line)
        convlog.show()
        scrollwin = gtk.ScrolledWindow()
        scrollwin.set_policy(gtk.POLICY_AUTOMATIC, gtk.POLICY_AUTOMATIC)
        scrollwin.add(convlog)
        scrollwin.show()
        textentry = gtk.TextView()
        textentry.set_wrap_mode(gtk.WRAP_WORD)
        textentry.connect("key_press_event", self.key_event, conv.conversationID)
        textentry.show()
        self.conversations[conv.conversationID] = [conv, convlog.get_buffer(), textentry.get_buffer()]
        vpaned.add1(scrollwin)
        vpaned.add2(textentry)
        vpaned.set_position(300)
        vpaned.show()
        self.notebook.append_page(vpaned, label)

    def delete_conversation(self, convID):
        page_id = self.convID_to_page(convID)
        self.notebook.remove_page(page_id)
        del self.conversations[convID]
        return

    def close_conversation(self, foo):
        convID = self.page_to_convID(self.notebook.get_current_page())
        conv = purple_pb2.Conversation()
        conv.conversationID = convID
        conv.accountID = 0
        rp.protosend(conv, "DeleteConversation")
        return
                
    def hilight_conv(self, convID, color):
        convname = self.conversations[convID][0].name
        page_id = self.convID_to_page(convID)
        label = self.notebook.get_tab_label(self.notebook.get_nth_page(page_id))
        label.set_markup("<span foreground=\""+color+"\">"+convname+"</span>")
        return

    def page_to_convID(self, page_num):
        convname = self.notebook.get_tab_label_text(self.notebook.get_nth_page(page_num))
        for convID in self.conversations:
            if self.conversations[convID][0].name == convname:
                return convID
    
    def convID_to_page(self, convID):
        convname = self.conversations[convID][0].name
        i = 0
        while(i <= self.notebook.get_n_pages()):
            if(self.notebook.get_tab_label_text(self.notebook.get_nth_page(i)) == convname):
                return i
            else:
                i = i+1

    def switch_event(self, notebook, page, page_num):
        self.hilight_conv(self.page_to_convID(page_num), "black")
        return

class BuddyList:
    # close the window and quit
    def delete_event(self, widget, event, data=None):
        gtk.main_quit()
        global listen_thread
        listen_thread.quit = True
        return False

    def __init__(self):
        self.buddies = dict()
        # Create a new window
        self.window = gtk.Window(gtk.WINDOW_TOPLEVEL)

        self.window.set_title("Remote Purple")

        self.window.set_size_request(300, 400)

        self.window.connect("delete_event", self.delete_event)

        # create a TreeStore with one string column to use as the model
                                    # Text  BG  Weight
        self.treestore = gtk.TreeStore(str, str, int, int)

        # we'll add some data now
        for account in rp.get_accounts():
            piter = self.treestore.append(None, ['%s' % account.ownpresence.alias, _COLORS[u"online"], 600, account.ownpresence.buddyID])
            for buddy in account.buddylist:
                self.buddies[buddy.buddyID] = ['%s' % buddy.alias, _COLORS[buddy.state], 400, buddy.buddyID]
                self.treestore.append(piter, self.buddies[buddy.buddyID])

        # create the TreeView using treestore
        self.treeview = gtk.TreeView(self.treestore)
        self.treeview.connect("row_activated", self.open_conversation)

        # create the TreeViewColumn to display the data
        self.tvcolumn = gtk.TreeViewColumn('Buddy list')

        # add tvcolumn to treeview
        self.treeview.append_column(self.tvcolumn)

        # create a CellRendererText to render the data
        self.cell = gtk.CellRendererText()

        # add the cell to the tvcolumn and allow it to expand
        self.tvcolumn.pack_start(self.cell, True)

        # set the cell "text" attribute to column 0 - retrieve text
        # from that column in treestore
        self.tvcolumn.add_attribute(self.cell, 'text', 0)
        self.tvcolumn.add_attribute(self.cell, 'background', 1)
        self.tvcolumn.add_attribute(self.cell, 'weight', 2)

        # make it searchable
        self.treeview.set_search_column(0)

        # Allow sorting on the column
        # self.tvcolumn.set_sort_column_id(0)

        # Allow drag and drop reordering of rows
        # self.treeview.set_reorderable(True)

        self.window.add(self.treeview)

        self.window.show_all()

    def main(self):
        # All PyGTK applications must have a gtk.main(). Control ends here
        # and waits for an event to occur (like a key press or mouse event).
        gtk.main()

    def update_buddy(self, buddyID, newstatus):
        buddyname = self.buddies[buddyID][0]
        print "Changed: "+buddyname+" ("+str(buddyID)+")"
        root_iter = self.treestore.get_iter_first()
        while(root_iter != None):
            child = self.treestore.iter_children(root_iter)
            while(child != None):
                if(self.treestore.get_value(child, 0) == buddyname):
                    print "Setting new color: "+ _COLORS[newstatus]+" ("+newstatus+")"
                    self.treestore.set_value(child, 1, _COLORS[newstatus])
                child = self.treestore.iter_next(child)
            root_iter = self.treestore.iter_next(root_iter)
        self.buddies[buddyID][1] = _COLORS[newstatus]
    
    def open_conversation(self, treeview, buddypath, viewcolumn):
        buddyiter = self.treestore.get_iter(buddypath)
        acciter = self.treestore.iter_parent(buddyiter)
        buddyname = self.treestore.get_value(buddyiter, 0)
        accID = self.treestore.get_value(acciter, 3)
        conv = purple_pb2.Conversation()
        conv.conversationID = self.treestore.get_value(buddyiter, 3)
        conv.accountID = accID
        conv.name = buddyname
        rp.protosend(conv, "NewConversation")
        return

def listen_loop():
    global blist, conversations
    while True:
        event = rp.listen_update()
        if(event[0] == "IM"):
            while((event[2].message.find("<FONT") == 0) and (event[2].message[-1] == ">")):
                event[2].message = event[2].message[event[2].message.find('>')+1:event[2].message.rfind('<')] # Strip <FONT>-crap
            gobject.idle_add(conversations.new_line, event[1], event[2])
            if(len(event[2].message) > 200):
                n = pynotify.Notification("New IM", event[2].sender+": "+ event[2].message[0:197]+"...")
            else:
                n = pynotify.Notification("New IM", event[2].sender+": "+event[2].message)
            n.show() # TODO: Don't show if user just sent the shown IM.
            time.sleep(0.1)
        if(event[0] == "NewConversation"):
            conversations.new_conversation(event[1])
        if(event[0] == "DeleteConversation"):
            conversations.delete_conversation(event[1].conversationID)
        if(event[0] == "BuddyState"):
            blist.update_buddy(event[1].buddyID, event[1].state)

# If the program is run directly or passed as an argument to the python
# interpreter then create a HelloWorld instance and show it
if __name__ == "__main__":
    conversations = Conversations()
    blist = BuddyList()
    listen_thread = threading.Thread(target = listen_loop)
    listen_thread.start()
    gobject.threads_init()
    gtk.main()
