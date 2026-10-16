# Sunset Chaser

This application should show us pictures from web cameras around the world. 
You should find web cameras near to the sun terminator line.

## Web Cameras provider

URL: https://api.windy.com/

## Application

I want to have in two pieces:
- Backend. Node.JS.
- Frontend. Ask me about a framework.

Use the standard approach for routing. Auth is not required.
Create a folder "sunset-chaser" and subfolders for the backend and the frontend.

## Tech stack

- Node.JS
- use .env to settings
- use DeepSeek as primary LLM. Store its serial key in .env

## Workflow

1. Find the actual position of the sun terminator line.
2. Find web cameras that are nearby of the sun terminator line. Count on latitude and duration of the sunset.
3. Fallback: always provide at least few cameras that are located in "day-time-zone" in big cities.


