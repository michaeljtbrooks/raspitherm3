/**
* 
* Raspitherm.js
* 
* 	jQuery routines to support Raspitherm
*/

// JS namespace
if(typeof(raspitherm) === "undefined") {
    raspitherm = {};
}

//Debouncing function. Rate limits the function calls
function debounce(func, wait, immediate) {
    let timeout;
    return function() {
        let context = this, args = arguments;
        let later = function() {
            timeout = null;
            if (!immediate) func.apply(context, args);
        };
        let callNow = immediate && !timeout;
        clearTimeout(timeout);
        timeout = setTimeout(later, wait);
        if (callNow) func.apply(context, args);
    };
}
raspitherm.debounce = debounce;

function resolve_state_int(state_str){
    // Turns the given state (identified by string) into an integer (0 or 1)
    if(state_str==="on" || state_str==="ON" || state_str==="On" || state_str==="1" || state_str===1 || state_str===true || state_str==="True"){
        return 1;
    }
    return 0;
}
function toggle_heat_ui($container, intended_state){
    // Toggles the given container's state (only if required!!)
    // @param $container: jQuery object containing the controls stuff
    // @param intended_state: "on" or "off"

    let clean_intended_state = resolve_state_int(intended_state);
    let clean_ui_state = resolve_state_int($container.data("status") || "off");
    let $off_icon = $container.find(".icon_off").first();
    let $on_icon = $container.find(".icon_on").first();
    let $toggle_switch = $container.find("input.toggle_checkbox").first();

    // Flip the UI to the correct state
    if(clean_intended_state !== clean_ui_state || true){  //Default to always execute
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
raspitherm.resolve_state_int = resolve_state_int;

$.fn.extend({
    "debounce":debounce,
    "toggle_heat_ui": toggle_heat_ui
});


function update_heating_ui_controls(current_hardware_settings){
	//Updates our heating control buttons to the given dict
	current_hardware_settings = current_hardware_settings || {"ch":"off", "hw":"off"};
	let debug = current_hardware_settings["debug"] || 0;
    let ch_actual_status = current_hardware_settings["ch"] || "off";
	let hw_actual_status = current_hardware_settings["hw"] || "off";
	let th_available = current_hardware_settings["th_available"] || 0;

	let $ch_container = $("#central_heating");
	let $hw_container = $("#hot_water");

    // Update the switch ui controls to reflect the hardware status
    $.fn.toggle_heat_ui($ch_container, ch_actual_status);
    $.fn.toggle_heat_ui($hw_container, hw_actual_status);

    // If we have temp/humidity, update indicator to suit
    let $central_heating_temperature_display = $("#central_heating_temperature_display");
    let current_temp_str = "--"
    if(th_available) {
        current_temp_str = current_hardware_settings["th_temp_c"] || "--";
    }
    $central_heating_temperature_display.html(current_temp_str);

    // IF central heating is off, hide the slider and target temp
    let $central_heating_target_temp_container = $("#central_heating_temperature_target");
    if(ch_actual_status === "off"){
        $central_heating_target_temp_container.hide();
    } else {
        $central_heating_target_temp_container.show();
    }

}
$.fn.extend({
    "update_heating_ui_controls": update_heating_ui_controls
});
raspitherm.update_heating_ui_controls = update_heating_ui_controls;


// Respond to user interactions:
$(document).ready(function(){

    // Switching a switch
    $(".toggle_checkbox").on("click", function(e){
		// Detects clicking a checkbox

		let $checkbox = $(this);
		$checkbox.removeClass("button_error");
		let post_click_status = $checkbox.prop("checked");
		let keyname = $checkbox.data("keyname");
		console.log(keyname+": "+post_click_status);

		let intended_post_click_hardware_state = "on";
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

	// Sliding a thermostat slider
    $("#central_heating_temperature_target_slider").on("input", function(e){
        let $target_temp_slider = $(this);
        let $central_heating_temperature_target_display = $("#central_heating_temperature_target_display");
        let target_temp = Number($target_temp_slider.val());
        // Limit to range:
        if(target_temp > 30.0){
            target_temp = 30.0;
            $target_temp_slider.val(target_temp);
        }
        if(target_temp < 5.0){
            target_temp = 5.0;
            $target_temp_slider.val(target_temp);
        }

        // Update the readable text
        $central_heating_temperature_target_display.html(target_temp);

        // TODO: fire off ajax to update the set point
    });

});

