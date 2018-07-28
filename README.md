# Raspitherm #

Raspberry Pi controlled hot water / central heating

![Raspitherm Web Interface](https://github.com/michaeljtbrooks/raspitherm/blob/master/docs/raspitherm_ui.png)

### What is this? ###
Raspitherm is a Python based controller for heating programmers. It allows you to turn your hot water and central heating on and off, via a very easy to use touch-friendly web interface.

* Turn on and off your hot water
* Turn on and off your central heating

### Requirements ###
1. Python & this repository
2. A network capable Raspberry Pi or Pi Zero W
3. A heating programmer with status LEDs you can tap, and manual override buttons you can emulate the press of. e.g. Danfoss FP715
4. 2 x MOSFETs 3.3v logic compatible. [I suggest IRLZ34N](https://www.aliexpress.com/wholesale?SearchText=IRLZ34N)
5. 4 x optoisolator gates
5. Prototyping matrix board / PCBs
6. 5V DC power supply to drive the Raspberry Pi
7. [Pigpio](http://abyz.me.uk/rpi/pigpio/index.html) to provide you with software pulse width modulation
8. 2 x 100R (one hundred ohm) current limiting resistors for input channel optoisolator LEDs
9. 2 x 500R (five hundred ohm) current limiting resistors for output channel optoisolators
10. 4 x 47k pull-down resistors 


### Hardware circuitry ###
Here's the circuit I used to connect to my Danfoss FP715S controller:

![Raspitherm Interface Circuit](https://github.com/michaeljtbrooks/raspitherm/blob/master/docs/Danfoss_RaspberryPi_interface_circuit.png)

Broadly speaking you have two input channels, and two output channels, each operating via an optoisolator to keep the Raspberry Pi and heating programmer separate.

Each input channel is monitoring the voltage across an indicator LED on the programmer. It drives an optoisolator which puts 3.3V into an input pin in the Raspberry Pi. One channel for hot water, the other for central heating.
Each output channel is emulating a button press. It switches an optoisolator on which shorts one side of the manual override button to its other side (thus emulating a button press).

Therefore you need a heating programmer that has indicator LEDs, and manual on/off toggle buttons. You need to tap the programmer's PCB.


### Software Installation ###
1. Get Raspian or Ubuntu running on your Raspberry Pi, with network connectivity working, and install essential packages:
```bash
sudo apt-get install build-essential unzip wget git
```
2. Install pigpio (see http://abyz.me.uk/rpi/pigpio/download.html)
```bash
wget https://github.com/joan2937/pigpio/archive/master.zip
unzip master.zip
cd pigpio-master
make
sudo make install
```
3. Download this *Raspitherm* repo to your Raspberry Pi
4. SSH into your Raspberry Pi. Change to the directory where you saved this repo
5. Install python virtual environments
```bash
sudo apt-get install python-pip 
sudo pip install virtualenv
```
6. Create a virtual environment to run Raspiled in, and activate it
```bash
virtualenv ./
source ./bin/activate
```
7. Install this repo's dependencies (may take 1- mins on a Raspberry Pi
```bash
pip install -r ./src/requirements.txt
```
8. Find out your Raspberry Pi's IP address:
```bash
ifconfig
```
9. Modify ./src/raspitherm.conf: change the constants for the Pins match which pins are you inputs and outputs for the hot water and central heating. PI_PORT should be left as 8888 as this is what Pigpiod is configured to use. If the file isn't present, run python ./raspitherm_listener.py to generate it.
10. Run the Pigpiod daemon:
```bash
sudo pigpiod
```
12. Run the Raspitherm server:
```bash
python ./src/raspitherm_listener.py
```
13. On your smartphone / another computer on the same local network, open your web browser and head to: http://<your.raspberry.pi.ip>:9090 e.g. http://192.168.0.233:9090 in my case

##### Optional stuff #####
If you want the Raspberry Pi to boot up and automatically run Raspitherm, you can add this command to /etc/rc.local:
```bash
/path/to/your/virtualenv/python /path/to/your/raspiled/src/raspitherm_listener.py
```
e.g. assuming you installed it in the /opt directory
```bash
/opt/raspitherm/env/bin/python /opt/raspitherm/src/raspitherm_listener.py
```


### Web Interface ###
#### http://<your.raspberry.pi.ip>:9090 ####

Practically idiot-proof! Click the radiator switch to turn the central heating on and off. Click the tap (faucet) switch to turn the hot water heating on and off.


### That's it! ###
Feel free to download the code, dick about with it, make something awesome. I am trying to create a home automation empire out of Raspberry Pis. You are very welcome to contribute.

Here are some ideas for improvements:
* Time based controls: You could set your programmer to have no on/off signals at all, then have the Raspberry Pi control it all (might need realtime clock if precision is your thing or the ntp daemon isn't working)
* Antipatory heating: The Raspberry Pi could download a weather forecast and fire up the heating only on the days when you are at home and it's likely to be cold
* Smart thermostat: Use a digital thermometer input to measure the temperature in the house, and use this to drive the Raspberry Pi's heating control
* IFTTT bindings: need to be careful about auth here, but you could have "if my phone location says I'm leaving work, turn on my hot water"
* Alarm linkage: When you're at home and have an alarm set, ensure the hot water + central heating goes 30 mins before your alarm is due to sound. Great for shift workers / erratic schedules!!


#### With thanks to ####
* Josue-Martinez-Moreno for contributing better logging and the config file architecture.
* Danfoss for putting handy test pads on their PCBs making tapping the board easy
* Ant323d for his [YouTube video showing how to tap a Danfoss heating programmer](https://www.youtube.com/watch?v=Guhf7eohl98)!
