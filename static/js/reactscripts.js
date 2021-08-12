// TODO: Don't use classes since it's supported only by modern browsers.
class ReactVar {
    constructor(initial_val) {
      this._val = initial_val;
      this.changed_from_initial = false;
      this.attached = [];
    }

    attach(cb, invoke_if_changed_from_initial) {
        this.attached.push(cb);
        if (this.changed_from_initial && invoke_if_changed_from_initial)
            cb();
    }

    notify() {
        this.changed_from_initial = true;

        for (var i = 0; i < this.attached.length; ++i) {
            const cb = this.attached[i]
            cb();
        }
    }

    get val() {
        return this._val;
    }

    set val(new_val) {
        if (this.val !== new_val || (new_val && new_val.constructor == Object)) {
            this._val = new_val;
            this.notify();
        }
    }
}

if (typeof Array.isArray === 'undefined') {
    react_check_array_func = function(obj) {
      return Object.prototype.toString.call(obj) === '[object Array]';
    }
} else {
    react_check_array_func = Array.isArray
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