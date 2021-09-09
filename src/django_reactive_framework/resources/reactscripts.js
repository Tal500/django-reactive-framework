// The doubly linked list(dll) is based on https://javascript.plainenglish.io/doubly-linked-lists-with-javascript-9c20a9dc4fb3

function __reactive_dll_push(self, val) {
    const newNode = {val:val,next:null,prev:null};
    if (self.head === null) {
        self.head = newNode;
        self.tail = newNode;
    } else {
        self.tail.next = newNode;
        newNode.prev = self.tail;
        self.tail = newNode;
    }
    return newNode;
}

function __reactive_remove_node(self, node) {
    if (node.prev === null) {
        if (self.head === node)// Must verify it since we might clear all earlier (it's legal)
            self.head = node.next;
    } else
        node.prev.next = node.next;
    
    if (node.next === null) {
        if (self.tail === node)// Must verify it since we might clear all earlier (it's legal)
            self.tail = node.prev;
    } else
        node.next.prev = node.prev;
}

var __reactive_check_array_func = Array.isArray
if (typeof __reactive_check_array_func === 'undefined') {
    __reactive_check_array_func = function(obj) {
      return Object.prototype.toString.call(obj) === '[object Array]';
    }
}

function __reactive_data(initial_val) {
    return {val:initial_val,changed_from_initial:false,attached:{head:null,tail:null}};
}

function __reactive_data_attach(self, cb, invoke_if_changed_from_initial) {
    const attachment = __reactive_dll_push(self.attached, cb);
    if (self.changed_from_initial && invoke_if_changed_from_initial)
        cb();
    
    return attachment;
}

function __reactive_data_detach(self, attachment) {
    __reactive_remove_node(self.attached,attachment);
}

function __reactive_data_notify(self) {
    self.changed_from_initial = true;

    var current = self.attached.head;
    while (current !== null) {
        current.val();
        current = current.next;
    }
}

function __reactive_data_set(self, new_val) {
    if (self.val !== new_val || (new_val && (new_val.constructor == Object || __reactive_check_array_func(new_val)))) {
        self.val = new_val;
        __reactive_data_notify(self);
        return true;
    } else
        return false;
}

function __reactive_print_html(obj) {
    function print_sub_element(obj) {
        if (typeof obj === "string")
            return "'" + obj + "'";
        else
            return __reactive_print_html(obj);
    }

    if (obj === null)
        return 'None';
    else if (obj === true)
        return 'True';
    else if (obj === false)
        return 'False';
    else if (__reactive_check_array_func(obj)) {
        if (obj.length == 0)
            return "[]"
        // otherwise

        var output = "";
        for (var i = 1; i < obj.length; ++i) {
                output += ", " + print_sub_element(obj[i]);
        }

        return "[" + print_sub_element(obj[0]) + output + "]";
    } else if (obj && obj.constructor == Object) {
        var output = "";
        var is_first = true;

        for (var key in obj) {
            if (obj.hasOwnProperty(key)) {
                if (is_first)
                    is_first = false
                else
                    output += ", "
                
                output += "'" + key.toString() + "': " + print_sub_element(obj[key])
            }
        }

        return "{" + output + "}";
    }
    else
        return obj.toString();
}