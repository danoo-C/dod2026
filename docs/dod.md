# DOD - den otvorenych dveri spseke 2026

### an ESP32 project paired with a webapp running on the local network.

## peripherials
- an individually addressable rgb strip -- directly connected
- a 4x16 lcd display -- i2c
- 8x8 led grid -- i2c

## what it does 
this is a project that lots of young people are going to see. 
lets be honest, these days the  15 year olds cannot hold focus for long. this project has to be the stupidest thing ever. the webapp will function as a controller for the rgb strip. i see a lot of potential in the rgb strip. 

### multiple apps in one webapp
1. youtube player and live generation of a light show on the rgb strip, a FFT on the 8x8 led grid and the display will works as a logging interface.

2. individual controll. you can controll the rgb strip, create fades or play with presets. each preset will have a lot of options for configuration, also the 8x8 grid will follow the vibe of the presets -- this needs to be thinked trought, what the 8x8 grod does in this indiviual controll.

- each app on the frontend will have a complicated looking loading screen, and also the logging on the lcd should look complicated. the purpose of this is to be really cool even tho the loading screens and the logging are completely fake. 

- the web app should look as modern and vibrant but still reasonable colors. the language is slovak on the page, but the logging on the lcd will be in english for complex looking

## technical spec
- the webapp will be run on a python fastapi server. the server runs on a notebook (i discussed this with my teacher and we settled on this option) -- the final product should be a dockerfile and one launch script for windows. 
- the notebook and esp32 communicate trough serial

- i honestly feel like the main logic should be on the fastapi backend and the esp 32 will be a bridge between the peripherals and notebook.
