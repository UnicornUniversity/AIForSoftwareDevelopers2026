# Drone Vision Lab

A classroom desktop application for DJI Tello control and computer-vision
comparison. One window combines a live/simulated camera, three vision families —
classical OpenCV thresholding, YOLO object detection and a local
vision-language model — supervised manual flight, scripted missions, a yaw-only
target tracker and an experiment recorder.

The application is **simulated by default**: it opens no drone socket, loads no
model and sends no flight command until the operator starts a source or connects.
Hardware mode is a command-line flag away, but the safety rules are the same in
both modes.

Everything runs on the machine: the camera feed, the detectors, the experiment
files and (when used) the Ollama model. No cloud API and no API key.

## What is here

| entry point | what it does |
| --- | --- |
| `drone-vision-lab` / `python -m drone_vision_lab` | Starts the PySide6 desktop application |
| `pytest` | 719 tests: domain, safety, adapters, workers and every tab, with no drone, GPU, model or network |
| `safety.py`, `mission.py`, `preset_missions.py`, `tracking.py`, `pursuit.py` | Qt-free decision modules, importable and testable without a display |

One window, six tabs and a dockable results panel:

| view | purpose |
| --- | --- |
| **Computer Vision Lab** | One camera source, three detectors, calibration, dry run, autonomous yaw tracking |
| **Tello Flight** | Live aircraft camera with all-class YOLO boxes; camera commands only |
| **Object detection && feedback** | Advisory pursuit rehearsal: a green box and the yaw decision the tracker *would* make |
| **Drone Control** | Connection, telemetry and explicit bounded manual steps |
| **Flight Missions** | An editable six-segment rectangular loop |
| **Preset Flight Missions** | Three read-only programs, including an apple-recognition observation |
| **Experiment Results** (dock) | Start/finish an experiment, read the metrics, export CSV or JSON |

## Quick start

Python 3.11 or newer (developed on 3.13). From this directory
(`week07/tello`):

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -e ".[all,dev]"

drone-vision-lab          # or: python -m drone_vision_lab
```

On macOS or Linux activate with `source .venv/bin/activate`.

The default build runs the simulated aircraft. Press **Connect (simulated)** on
Drone Control, choose **Simulated camera** in the Computer Vision Lab, and the
whole workflow — calibration, dry run, missions, tracking — can be exercised
without hardware.

To fly a real Tello:

```powershell
drone-vision-lab --tello
# or set the environment variable:
$env:DRONE_VISION_LAB_DRONE = "tello"; drone-vision-lab
```

Connect the laptop to the aircraft's `TELLO-xxxx` Wi-Fi first. Connecting sends
the SDK `command` handshake only; it never takes off. See
[Tello hardware](#tello-hardware) for the network and firewall details.

### Optional extras

| extra | brings | needed for |
| --- | --- | --- |
| *(core)* | PySide6, NumPy | the window, the state model, the simulated aircraft |
| `vision` | `opencv-python` | colour calibration, file playback, VLM image encoding |
| `yolo` | `ultralytics` (and PyTorch) | YOLO detection on any tab |
| `hardware` | `av` (PyAV) | decoding the live Tello H.264 camera stream |
| `gamepad` | `pygame` | retained for a future lesson; **not wired into this build** |
| `dev` | pytest, pytest-cov, ruff, mypy | the test suite and linters |

`.[all]` is `vision,yolo,hardware`. Missing optional packages disable only the
feature that needs them: the application still starts and says which extra to
install.

### YOLO weights

YOLO weights are **not committed** (`*.pt` is gitignored). The YOLO settings
dialog accepts any local `.pt` file and looks first in the project root and
`models/`. A confirmed **Download YOLO11n weights…** button fetches the official
Ultralytics checkpoint and states its AGPL-3.0 licence before downloading.
Nothing is downloaded silently.

## How it works

```text
app.main ─► config (paths, env, SafetyLimits) ─► container.build_default_services
                                                    │
                    ┌───────────────────────────────┴────────────────────────────┐
                    ▼                                                            ▼
        simulated aircraft OR Tello adapter                  video source factory
        (CommandChannel 8889, state 8890,                     synthetic | file | Tello
         video 11111)                                                 │
                    │                                        FramePump (thread)
                    │                                                 ▼
                    │                                          active tab preview
                    │                                                 │
                    │                              ┌──────────────────┼──────────────────┐
                    │                              ▼                  ▼                  ▼
                    │                         OpenCV / YOLO      VLM poller        tracking session
                    │                         (thread pool)      (Ollama, periodic)  (yaw decisions)
                    │                              │                  │                  │
                    ▼                              ▼                  ▼                  ▼
              DroneAdapter ◄──────── MissionRunner / PresetRunner / ManualController / TrackingController
                    │
                    ▼
          AppStateStore (thread-safe snapshot) ─► StateBridge ─► every tab
```

Two rules keep the tabs consistent:

- **One frame source, one owner.** The Tello camera listens on UDP 11111, which
  is exclusive. Whichever tab starts a Tello source owns it; the others refuse
  to start until it is stopped. A local file or synthetic source has the same
  ownership rule so two tabs cannot silently compare different moments.
- **One state store.** Every command result, telemetry update, dry run and
  safety transition lands in `AppStateStore`. Tabs render an immutable snapshot
  and never keep their own copy of "is it flying?".

Heavy work is off the GUI thread: `FramePump` decodes, `CallableRunner` runs
detection/inference and every UDP wait on the Qt thread pool, and the Tello
receivers own their own threads. Each runner allows one job in flight and drops
frames rather than queueing a backlog.

## The tabs

### Computer Vision Lab

The comparison bench. Choose a source — synthetic camera, local video file or
the Tello camera — then one of four modes:

| mode | what runs | when |
| --- | --- | --- |
| OpenCV | HSV threshold + morphology + largest contours | every available frame |
| YOLO | Ultralytics, filtered to the configured target class | every available frame |
| VLM | Ollama vision model, one question per tick | on the configured interval, default 1 s |
| Comparison | OpenCV and YOLO on *the same frame*, plus the latest VLM answer | every available frame |

The results table shows status, latency, confidence and result age for each
algorithm. Confidence is printed only when an algorithm produced one: OpenCV and
the VLM show `N/A`, because thresholding and a model's self-report are not
calibrated scores. The VLM row is labelled with the age of its answer and marked
stale when it is older than a few intervals.

The guided workflow is **source → configure/calibrate → dry run → ready**:

1. **Calibrate** samples the target colour from the current frame. Drag a box
   for a local sample, or let auto-calibration search the largest strongly
   coloured region; sliders refine the mask live. The saved range belongs to the
   active profile, not to a universal "green".
2. **YOLO settings…** loads local weights, reads the model's own class list,
   chooses the target class (default `apple`) and can run one test detection on
   the current frame. A model is staged until **Save**.
3. **VLM settings…** checks the local Ollama service, lists models, verifies
   image support and loads the model. The prompt template asks for one JSON
   object with a normalized box; answers are parsed defensively and shown with
   their age. The VLM is advisory and has no path to flight control.
4. **Dry run** runs OpenCV and/or YOLO on one frozen frame. Only a detector
   that found a target can unlock tracking; the VLM can never pass a dry run.

### Tello Flight

The operator view: live aircraft camera and YOLO marking **every class** the
loaded model knows, not just the target class. It is display-only. The tab sends
only `streamon` and `streamoff`; it never takes off, lands, moves, records or
feeds a detection into flight control.

### Object detection && feedback

A rehearsal for a Tello that cannot take off (the classroom unit reports a
sensor error). Show an apple to the camera or a video file; YOLO draws a green
box and `PursuitAdvisor` prints the decision the yaw-only tracker *would* make
as the target moves left and right.

This tab has no flight command, no arming, no dry run and no recording. Its only
commands are `streamon`/`streamoff` for the Tello camera. Every decision line
begins with **ADVISORY ONLY** and states that no command is (or was) sent.

### Drone Control

Connection, telemetry and supervised manual flight:

- **Connect** performs the SDK handshake and starts the telemetry receiver.
  It does not take off.
- **Take control** declares this desktop as the controller and warns that the
  phone app must not be flying at the same time.
- Each input sends **one bounded step**, not a continuous stick feed: 30 cm
  translation, 15° yaw, 30 cm/s, with a 0.5 s minimum gap. Keyboard: `W`/`S`
  forward/back, `A`/`D` left/right, `Q`/`E` yaw, `R`/`F` up/down. Takeoff asks
  for confirmation; Land is a separate button.
- Telemetry shows battery, height and the age of the last report. Stale values
  are marked stale, and the safety gates refuse them. If the command channel
  stops responding, the state becomes **Communication lost** — never "landed".
- **Gamepad input is not wired into this build.** The mapping module and pygame
  adapter remain on disk for a later lesson.

### Flight Missions

A rectangular loop flown in a fixed order: takeoff (with an optional climb),
left, forward, right, backward, land. Distances, speed and pauses are editable
within the conservative limits and validated on every change. **Preview** shows
the plan and a conservative time estimate without sending anything; **Execute
mission** asks for explicit confirmation first.

**Stop mission** stops issuing new segments and does not land; the command
already in flight finishes. A standard Tello has no reliable indoor global
position, so the loop is described as approximate — never as a return to the
exact start point.

### Preset Flight Missions

Three read-only programs:

| program | steps |
| --- | --- |
| Take off, hover 3 s, land | the shortest useful program and the first to try |
| Four left turns — 30 cm legs | four turns and four forward legs, about 1.2 m of travel |
| Take off, hold, recognize an apple | climbs 50 cm to about 1.5 m, hovers while YOLO marks the target, then lands |

The apple program needs hardware mode, a live Tello camera and a loaded YOLO
model; it opens the camera **before** takeoff and sends no takeoff if the camera
fails. An observation holds position without a flight command, so the aircraft
hovers on its own. Because a standard Tello lands itself after 15 s without any
command, long holds and observations send a bare `command` keepalive every 5 s;
it moves nothing.

Preset programs are fixed and validated like missions. **Stop program** never
lands. The program's own landing remains the fallback if the operator does not
press **Emergency Land** first.

### Experiment Results

Reachable from **View → Experiment Results** (hidden by default so the tabs get
the workspace). Start an experiment, run a dry run or a tracking session, finish
it, then export the recorded measurements as CSV or JSON.

Ten metrics are defined in `experiment.py`: frames analyzed, detections,
detection rate, target-loss events, detector errors, mean and P95 latency,
analysis rate, mean confidence and tracking stability. A metric that cannot be
measured is exported as `N/A` with the reason in its Note column — never as
zero. Exports are produced from the saved experiment file, not from the live
session, so an export cannot disagree with what was recorded. No frame, image or
video is saved.

## Safety model

The legal state transitions live in `safety.py`; the state enum and thread-safe
store live in `state.py`. The table is deliberately conservative:

- Connecting reaches **Connected grounded**. The grounded workflow is ordered
  camera → calibration → dry run → arming, and nothing in the transition table
  takes off or arms by itself.
- **Arm autonomy** only permits a later **Start Tracking**. It sends no command
  and does not take off.
- Tracking starts only from **Flying manual**, after a successful dry run for
  the selected detector and an explicit arm.
- A landing request is a one-way door until independent evidence arrives.
  **Landing confirmed** requires telemetry received *after* the acknowledgement
  reporting height 0. An `ok` reply alone never proves the aircraft is down.
- A lost command channel goes to **Communication lost**, never to a state that
  implies a landing.
- **Fault** follows a program whose landing was not confirmed. It can only be
  left by reconnecting or disconnecting; it never silently resumes flight.

Command results distinguish what the application actually knows:

| status | meaning |
| --- | --- |
| `REJECTED` | refused locally by a safety check; nothing was transmitted |
| `REQUESTED` | accepted and queued, not yet transmitted |
| `SENT` | transmitted and acknowledged; the state change is not confirmed |
| `CONFIRMED` | transmitted *and* independently observed (telemetry, for landing) |
| `FAILED` | transmission failed or the aircraft replied with an error |
| `TIMEOUT` | no reply; the outcome is unknown |

**Emergency Land** sits in the top bar on every tab and is never hidden. It
sends the standard `land` command ahead of everything queued; it never cuts the
motors and is never reported as confirmed. When the command channel is gone it
says the command could not be sent, because the laptop cannot force a landing
offline.

Other invariants:

- Takeoff requires a fresh battery report of at least 10 %. Movement legs
  re-check in flight and abort or refuse below 20 %.
- Telemetry older than 1 s is stale. Stale values are displayed but never used
  to satisfy a takeoff, vertical-control or mission gate.
- Climbing is bounded by the reported height and the 150 cm altitude limit;
  descending into the ground is refused (use Land).
- Closing the application sends no takeoff, landing or motor-stop command. An
  aircraft that is still airborne stays airborne; a camera stream that is still
  running gets a best-effort `streamoff`.

## Vision detectors

All three satisfy one small `Detector` protocol and return the same
`DetectionResult`, so the comparison table and overlay do not special-case an
algorithm.

- **OpenCV** (`adapters/vision/opencv_detector.py`) blurs, converts to HSV,
  thresholds one or more ranges (hue may wrap through red), applies morphology
  and takes the largest contours. It deliberately reports **no confidence**;
  the metrics dict carries the mask area and fill ratio instead.
- **YOLO** (`adapters/vision/yolo_detector.py`) uses Ultralytics, reads class
  names from the loaded model and normalizes boxes to `[0, 1]`. `device="auto"`
  picks CUDA when PyTorch reports it, otherwise CPU; the dialog shows which one
  is active. A broken CUDA probe is logged and reported as a probe failure, not
  as "no GPU".
- **VLM** (`adapters/vlm/`) sends a JPEG (longest side capped at 640 px) to a
  local Ollama vision model on a timer. The prompt asks for one JSON object;
  `vlm_parsing.py` validates `visible`, `label` and `bbox`, strips control
  characters and caps display text. A malformed answer becomes a detector error,
  not a crash. The model's self-reported score is never used as a confidence.

## Autonomous tracking

`TrackingController` is yaw-only. It takes the largest detected box, computes
the normalized horizontal error and asks for a proportional yaw step, with a
±0.10 deadband, 5–20° steps and a 0.6 s minimum gap. It never moves forward,
backward or changes altitude, and it never calls the drone itself — the tab
submits each step through a worker.

A session ends on a stale result, a detector failure, three consecutive missed
targets or the 60 s session limit. **Stop Tracking** stops issuing yaw
corrections and does not land; the tab says so and points at Land and Emergency
Land. Manual input stops tracking before it sends its own step, and so do a
source stop, a mode change and a detector reconfiguration.

The VLM is rejected at construction time: only OpenCV and YOLO can create a
tracking controller, so there is deliberately no path from a model's text answer
to flight control.

## Tello hardware

The adapter speaks only the documented **standard Tello** SDK; there are no EDU
mission pads and no `mon`/`moff` verbs.

| UDP port | direction | purpose |
| --- | --- | --- |
| 8889 | sent to `192.168.10.1` | commands and their `ok`/`error` replies |
| 8890 | received on this laptop | state packets (`bat:87;h:0;…`) about 10×/s |
| 11111 | received on this laptop | H.264 video datagrams |

The command channel is serialized and rate-limited. The SDK has no request ids,
so replies are correlated by arrival order; a datagram queued before a command
was transmitted is discarded instead of being read as its acknowledgement.
Packets from any host other than the configured aircraft are ignored, for
commands, telemetry and video alike.

If telemetry cannot bind 8890 (another Tello tool owns it, or the firewall
blocks it), the application says telemetry is unavailable and shows "not
reported" rather than a guessed battery. Takeoff is then blocked. **Help → Tello
connection check…** runs read-only laptop-side checks: route to the Tello
network, command socket, telemetry port, video port and firewall guidance. It
sends no UDP packet; only a `command` handshake proves reachability.

A standard Tello does not arbitrate between controllers. If the DJI phone app
and this application both send commands, both take effect; close the phone app's
control session before flying from here.

## Configuration

### Command line

```powershell
drone-vision-lab                    # simulated aircraft (default)
drone-vision-lab --tello            # standard Tello adapter
drone-vision-lab --simulated        # force simulation
drone-vision-lab --debug            # DEBUG to console and log file
drone-vision-lab --log-level WARNING
```

### Environment

| variable | default | effect |
| --- | --- | --- |
| `DRONE_VISION_LAB_DRONE` | `simulated` | `tello`/`hardware`/`real`, or `simulated`/`sim`/`fake`; unknown values fall back to simulation with a visible note |
| `DRONE_VISION_LAB_HOME` | `%LOCALAPPDATA%\DroneVisionLab` | root for logs, profiles and results |
| `DRONE_VISION_LAB_LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR`; a flag wins over the variable |

An explicit `--tello` or `--simulated` wins over the environment variable.

### Conservative limits

`config.SafetyLimits` holds the classroom defaults used by validation and the
flight runners:

| setting | default |
| --- | --- |
| takeoff battery floor | 10 % |
| in-flight movement floor | 20 % |
| maximum altitude | 150 cm |
| maximum segment distance | 100 cm |
| maximum speed | 50 cm/s |
| maximum mission duration | 120 s |
| maximum tracking session | 60 s |
| command timeout | 5 s |
| minimum gap between commands | 0.1 s |
| telemetry freshness | 1 s |
| takeoff settle wait | 5 s |

The Tello SDK's own bounds still apply: movement is 20–500 cm, speed 10–100 cm/s
and yaw 1–360°. A plan outside the configured limits is rejected, never
silently adjusted.

### Data locations

| path | contents |
| --- | --- |
| `%LOCALAPPDATA%\DroneVisionLab\logs\drone-vision-lab.log` | rotating log, 2 MB × 5, with `key=value` context |
| `%LOCALAPPDATA%\DroneVisionLab\profiles\*.json` | one portable profile per file |
| `%LOCALAPPDATA%\DroneVisionLab\results\*.json` | one experiment per file |
| `video\` | starting folder for **Load video…**; gitignored |
| any local `*.pt` | YOLO weights chosen in the dialog; gitignored |

`DRONE_VISION_LAB_HOME` redirects the first three. The test suite points it at a
temporary directory, so tests never touch real profiles, results or logs.

### Profiles

**File → Experiment Profiles…** creates, renames, duplicates, deletes, saves and
loads profiles. A profile stores detector settings (`opencv`, `yolo`, `vlm`),
the last source kind/path and a dry-run summary. Loading installs settings into
the running application but **never starts a video source, loads a model over
the network or sends a command**. A broken section is reported and skipped
without blocking the other sections.

### Ollama

The VLM is optional. Start a local service and install a vision-capable model:

```powershell
ollama serve
ollama pull llava
```

The default base URL is `http://127.0.0.1:11434`; the dialog can point at another
address. Model loading is warmed up once so the request timeout measures
inference, not disk and VRAM. For models that report a `thinking` capability,
the chain of thought is switched off: an advisory answer must stay within a
classroom-perceptible latency.

## Tests

```powershell
.venv\Scripts\python.exe -m pytest
# 719 passed, 4 skipped in about 9 s
```

The suite forces Qt onto the offscreen platform, redirects
`DRONE_VISION_LAB_HOME` to a temporary directory and needs no display, drone,
GPU, model, Ollama service or network. It covers the domain types, the safety
transition table, mission/preset validation and runners, the Tello protocol and
channel correlation, the fake drone, tracking and pursuit geometry, storage and
profiles, every worker, and each tab through both UI and integration tests.

Four opt-in tests are skipped by default because they need real resources:

```powershell
# Physical Tello on the ground; sends the handshake and camera commands only,
# never takeoff, movement, arming or a settings change.
$env:TELLO_HARDWARE_TEST = "1"
.venv\Scripts\python.exe -m pytest -m hardware -s

# A real local Ollama vision model.
$env:DRONE_VISION_LAB_OLLAMA_MODEL = "llava"
.venv\Scripts\python.exe -m pytest -m ollama -s

# A real local YOLO weights file.
$env:DRONE_VISION_LAB_YOLO_MODEL = "C:\path\to\yolo11n.pt"
.venv\Scripts\python.exe -m pytest -m model -s
```

`ruff check` and `mypy` are installed by the `dev` extra; `mypy` is configured
for `src` in `pyproject.toml`.

## Layout

| path | purpose |
| --- | --- |
| `src/drone_vision_lab/app.py` | QApplication bootstrap, CLI flags, exception hook |
| `src/drone_vision_lab/container.py` | composition root; selects the simulated or Tello aircraft |
| `src/drone_vision_lab/config.py` | identity, paths, environment overrides, `SafetyLimits` |
| `src/drone_vision_lab/domain.py` | `Frame`, `BoundingBox`, `Detection`, `Telemetry`, command status |
| `src/drone_vision_lab/state.py` | thread-safe `AppStateStore` and immutable snapshots |
| `src/drone_vision_lab/safety.py` | legal safety-state transitions and `SafetyStateMachine` |
| `src/drone_vision_lab/manual_control.py` | bounded manual commands and telemetry gates (Qt-free) |
| `src/drone_vision_lab/mission.py` | six-segment mission validation and `MissionRunner` |
| `src/drone_vision_lab/preset_missions.py` | fixed programs and `PresetRunner` |
| `src/drone_vision_lab/tracking.py` | yaw-only `TrackingController` and decision geometry |
| `src/drone_vision_lab/pursuit.py` | advisory-only pursuit rehearsal |
| `src/drone_vision_lab/experiment.py` | metric definitions and the live experiment session |
| `src/drone_vision_lab/logging_setup.py` | console + rotating file handlers with structured context |
| `src/drone_vision_lab/adapters/drone/` | command channel, state receiver, H.264 video receiver, protocol, diagnostics |
| `src/drone_vision_lab/adapters/video/` | file and Tello camera sources behind one contract |
| `src/drone_vision_lab/adapters/vision/` | OpenCV calibration/detector and Ultralytics YOLO |
| `src/drone_vision_lab/adapters/vlm/` | Ollama client, VLM detector and defensive answer parsing |
| `src/drone_vision_lab/adapters/storage/` | JSON profile and experiment repositories |
| `src/drone_vision_lab/fakes/` | simulated aircraft, synthetic camera and test doubles |
| `src/drone_vision_lab/interfaces/` | Protocols every implementation satisfies |
| `src/drone_vision_lab/ui/` | main window, six tabs, dialogs, overlays and video session |
| `src/drone_vision_lab/workers/` | frame pump, one-shot runner and VLM poller |
| `tests/` | 719 tests, all offline; opt-in hardware/model/Ollama checks |

## Notes and limitations

- **Windows-first.** The path defaults, PowerShell setup and Tello network
  checks target Windows classroom machines. The Qt code is portable; on macOS
  or Linux adjust the activation command and the per-user data location.
- **No cloud calls.** After setup, the only network traffic is to the Tello on
  its own Wi-Fi network and to a local Ollama service if the VLM is used.
- **No video recording.** No tab writes frames, images or video. The camera
  receiver never opens a file, so the rule holds by construction. Only
  experiment metrics are persisted, plus logs and profiles.
- **No obstacle avoidance.** Tracking yaws toward a box. It does not detect
  obstacles, guarantee clearance or keep distance. Mission and preset loops are
  open-loop and approximate; a standard Tello has no reliable indoor global
  position and does not return to its exact start point.
- **Keep the aircraft in sight.** The application cannot see the room, and
  `SENT` is not evidence that a movement or landing happened. Emergency Land is
  one button; visual confirmation remains the operator's job.
- **One Wi-Fi adapter cannot be on two networks.** If the laptop has a single
  Wi-Fi card, it cannot stay on the internet and the Tello network at the same
  time. Use a second adapter or disconnect from the internet for the flight.
- **Firewall and ports.** Allow the Python interpreter or packaged application
  on Private networks for UDP 8889/8890/11111. A blocked inbound rule usually
  appears as a command timeout, not a clear firewall error.
- **Telemetry is optional, takeoff is not.** Losing the state receiver leaves
  battery "not reported" and blocks takeoff; it does not block landing.
- **The live camera needs PyAV.** H.264 decoding is single-threaded on purpose:
  the slice-threaded decoder can fault natively on the truncated packets of a
  lossy UDP stream (PyAV issue #2344), and a native crash cannot be caught in
  Python. Without PyAV the rest of the application still runs.
- **The gamepad extra is dormant.** `gamepad.py`, the pygame adapter and the
  fake remain on disk for a later lesson, but this build imports no pygame and
  reads no controller input.
- **YOLO weights are not shipped.** They are large and licensed AGPL-3.0; the
  dialog makes the licence and the download explicit. A model file that is
  missing, corrupt or incompatible is reported, never replaced silently.
- **Simulation is honest about itself.** The simulated aircraft records commands
  and reports 87 % battery; it does not model aerodynamics, cameras or failure
  modes. The synthetic camera is a moving green square — useful for a pipeline,
  not for judging detector accuracy.
- **A model answer is not a measurement.** VLM text is untrusted display data,
  stripped of control characters and capped in length. It never gates a dry run,
  arms anything, or reaches a flight controller.
