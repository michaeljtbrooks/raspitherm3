#!/bin/bash
# Sysinfo - Useful information about your Raspberry Pi in one place

show_help()
{
	 echo ""
	 echo "sysinfo - useful information about your Raspberry Pi in one place!"
	 echo "Usage:"
	 echo "    sysinfo [item]"
	 echo ""
	 echo "Items:"
	 echo "    kernel        Current kernel details"
	 echo "    linux         Current kernel details"
	 echo ""
	 echo "    hostname      Network host name"
	 echo "    name          Network host name"
	 echo ""
	 echo "    distro        The Linux distro including version"
	 echo "    release       The Linux distro including version"
	 echo "    lsb_release   The Linux distro including version"
	 echo "    lsb_release   The Linux distro including version"
	 echo ""
	 echo "    version       The Linux distro version and kernel version"
	 echo "    os            The Linux distro version and kernel version"
	 echo "    os-version    The Linux distro version and kernel version"
	 echo "    osversion     The Linux distro version and kernel version"
	 echo ""
	 echo "    space         The amount of disk space available and used"
	 echo "    disk          The amount of disk space available and used"
	 echo "    storage       The amount of disk space available and used"
	 echo ""
	 echo "    disk-ids      Storage devices, partitions and space used"
	 echo "    disk-id       Storage devices, partitions and space used"
	 echo "    diskids       Storage devices, partitions and space used"
	 echo "    diskid        Storage devices, partitions and space used"
	 echo "    blkids        Storage devices, partitions and space used"
	 echo "    lsblk         Storage devices, partitions and space used"
	 echo "    uuid          Storage devices, partitions and space used"
	 echo "    uuids         Storage devices, partitions and space used"
	 echo "    hdd           Storage devices, partitions and space used"
	 echo "    hdds          Storage devices, partitions and space used"
	 echo "    sdd           Storage devices, partitions and space used"
	 echo "    sdds          Storage devices, partitions and space used"
	 echo ""
	 echo "    memory        The amount of RAM used and free"
	 echo "    ram           The amount of RAM used and free"
	 echo "    mem           The amount of RAM used and free"
	 echo ""
	 echo "    signal        Wifi network and signal strength"
	 echo "    wifi          Wifi network and signal strength"
	 echo ""
	 echo ""
	 echo "    all           Show everything above"
	 echo ""
	 echo "    signal-all    All detected wifi networks and signal strength (sudo only)"
	 echo "    wifi-all      All detected wifi networks and signal strength (sudo only)"
	 echo ""
}

# Detect a -h help call
while getopts ":h" option; do
   case $option in
      h | help) # display Help
         show_help
         exit;;
   esac
done

# Ensure at least one item argument
if [ -z "$1" ]
  then
    echo "    sysinfo - ERROR - missing item argument"
    echo "    Please state what you want information about!"
    show_help
    exit 1
fi


show_temperatures() {
	if [ -x /opt/vc/bin/vcgencmd ]
	  then
		/opt/vc/bin/vcgencmd measure_temp
	  else
		if ! command -v sensors &> /dev/null
		  then
			echo "No temperature sensors available."
		  else
			sensors
		fi
	fi
}


# Run the function
case $1 in 
	
	kernel | linux)
		uname -a
		;;
	
	hostname | name)
		uname -n
		;;
	
	temp | temperature)
		show_temperatures
		;;
	
	signal | wifi)
		iwlist wlan0 scan | egrep "ESSID|Signal"
		;;
	
	signal-all | wifi-all)
		sudo iwlist wlan0 scan | egrep "Cell|ESSID|Signal|Rates"
		;;
	
	memory | ram | mem)
		free -h
		;;

	space | disk | storage | disks)
		df -h
		;;

	disk-ids | disk-id | diskids | diskid | blkids | lsblk | uuid | uuids | hdd | hdds | sdd | sdds)
		lsblk -f
		;;
	
	distro | release | lsb_release | lsbrelease)
		lsb_release -a
		;;	
	
	version | os | os-version | osversion)
		uname -a
		lsb_release -a
		;;
	
	all )
		echo "sysinfo --- All information ----"
		uname -a
		lsb_release -a
		echo ""
		lsblk -f
		echo ""
		df -h
		echo ""
		free -h
		echo ""
		iwlist wlan0 scan | egrep "ESSID|Signal"
		echo ""
		show_temperatures
		;;
	
	*)
		echo "    sysinfo - ERROR - item not recognised"
		show_help
		exit 1
		;;
esac
	
