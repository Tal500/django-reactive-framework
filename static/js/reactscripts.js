// TODO: Don't use classes since it's supported only by modern browsers.

// Based on https://javascript.plainenglish.io/doubly-linked-lists-with-javascript-9c20a9dc4fb3
class Node {
    constructor(val) {
        this.val = val;
        this.next = null;
        this.prev = null;
    }
}

class DoublyLinkedList {
    constructor() {
        this.head = null;
        this.tail = null;
    }

    push(val) {
        const newNode = new Node(val);
        if (this.head === null) {
            this.head = newNode;
            this.tail = newNode;
        } else {
            this.tail.next = newNode;
            newNode.prev = this.tail;
            this.tail = newNode;
        }
        return newNode;
    }

    remove_node(node) {
        if (node.prev === null)
            this.head = node.next;
        else
            node.prev.next = node.next;
        
        if (node.next === null)
            this.tail = node.prev;
        else
            node.next.prev = node.prev;
    }
}

var react_check_array_func = Array.isArray
if (typeof react_check_array_func === 'undefined') {
    react_check_array_func = function(obj) {
      return Object.prototype.toString.call(obj) === '[object Array]';
    }
}

class ReactVar {
    constructor(initial_val) {
      this._val = initial_val;
      this.changed_from_initial = false;
      this.attached = new DoublyLinkedList();
    }

    attach(cb, invoke_if_changed_from_initial) {
        const attachment = this.attached.push(cb);
        if (this.changed_from_initial && invoke_if_changed_from_initial)
            cb();
        
        return attachment;
    }

    detach(attachment) {
        this.attached.remove_node(attachment)
    }

    notify() {
        this.changed_from_initial = true;

        var current = this.attached.head;
        while (current !== null) {
            current.val();
            current = current.next;
        }
    }

    get val() {
        return this._val;
    }

    set val(new_val) {
        if (this.val !== new_val || (new_val && (new_val.constructor == Object || react_check_array_func(new_val)))) {
            this._val = new_val;
            this.notify();
        }
    }
}

function react_print_html(obj) {
    function print_sub_element(obj) {
        if (typeof obj === "string")
            return "'" + obj + "'";
        else
            return react_print_html(obj);
    }

    if (obj === null)
        return 'None';
    else if (obj === true)
        return 'True';
    else if (obj === false)
        return 'False';
    else if (react_check_array_func(obj)) {
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