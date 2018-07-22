/**
* 
* Raspitherm.js
* 
* 	jQuery routines to support Raspitherm
*/


//Debouncing function. Rate limits the function calls
function debounce(func, wait, immediate) {
    var timeout;
    return function() {
        var context = this, args = arguments;
        var later = function() {
            timeout = null;
            if (!immediate) func.apply(context, args);
        };
        var callNow = immediate && !timeout;
        clearTimeout(timeout);
        timeout = setTimeout(later, wait);
        if (callNow) func.apply(context, args);
    };
};
function resolve_state_int(state_str){
    // Turns the given state (identified by string) into an integer (0 or 1)
    if(state_str=="on" || state_str=="ON" || state_str=="On" || state_str=="1" || state_str==1 || state_str==true || state_str=="True"){
        return 1;
    }
    return 0;
}
function toggle_heat_ui($container, intended_state){
    // Toggles the given container's state (only if required!!)
    // @param $container: jQuery object containing the controls stuff
    // @param intended_state: "on" or "off"

    var clean_intended_state = resolve_state_int(intended_state);
    var clean_ui_state = resolve_state_int($container.data("status") || "off");
    var $off_icon = $container.find(".icon_off").first();
    var $on_icon = $container.find(".icon_on").first();
    var $toggle_switch = $container.find("input.toggle_checkbox").first();

    // Flip the UI to the correct state
    if(clean_intended_state != clean_ui_state || true){  //Default to always execute
        if(clean_intended_state){ // Going on!!
            console.log($container.attr("id")+" going ON");
            $container.data("status","on");
            $off_icon.hide(0);
            $on_icon.show(0);
            $toggle_switch.attr("checked","checked"); //flip the toggle switch on
            $toggle_switch.prop("checked",true);
        } else {  // Going off!!
            console.log($container.attr("id")+" going OFF");
            $container.data("status","off");
            $on_icon.hide(0);
            $off_icon.show(0);
            $toggle_switch.removeAttr("checked"); //flip the toggle switch off
            $toggle_switch.prop("checked",false);
        }
    }

}
$.fn.extend({
    "debounce":debounce,
    "toggle_heat_ui": toggle_heat_ui
});


function update_heating_ui_controls(current_hardware_settings){
	//Updates our heating control buttons to the given dict
	current_hardware_settings = current_hardware_settings || {"ch":"off", "hw":"off"};
	var ch_actual_status = current_hardware_settings["ch"] || "off";
	var hw_actual_status = current_hardware_settings["hw"] || "off";

	var $ch_container = $("#central_heating");
	var $hw_container = $("#hot_water");

    // Update the ui controls to reflect the hardware status
    $.fn.toggle_heat_ui($ch_container, ch_actual_status);
    $.fn.toggle_heat_ui($hw_container, hw_actual_status);
};
$.fn.extend({
    "update_heating_ui_controls": update_heating_ui_controls
});


// Respond to :
$(document).ready(function(){
	$(".toggle_checkbox").on("click", function(e){
		// Detects clicking a checkbox

		var $checkbox = $(this);
		$checkbox.removeClass("button_error");
		var post_click_status = $checkbox.prop("checked");
		var keyname = $checkbox.data("keyname");
		console.log(keyname+": "+post_click_status);

		var intended_post_click_hardware_state = "on";
		if(!post_click_status){
		    intended_post_click_hardware_state = "off";
		}

		$.fn.debounce( //Debounced to prevent excessive AJAX calls
            $.ajax({ // Fire off ajax to actually change that state!!
                url: "/?"+ keyname + '=' + intended_post_click_hardware_state,
                success: function(latest_hardware_state_data){
                    console.log(latest_hardware_state_data);
                    $.fn.update_heating_ui_controls(latest_hardware_state_data); // Update UI to reflect changes
                },
                error: function(data){
                	$checkbox.addClass("button_error");
                },
                dataType: "json"
            }),
	    250); //Debounce delay ms
            
	});
});





