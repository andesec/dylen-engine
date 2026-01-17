import json
from app.schema.validate_lesson import validate_lesson

json_payload = {
  "title": "Mechanisms Behind AirPods Functionality",
  "blocks": [ {
  "section": "Mechanisms Behind AirPods Functionality",
  "items": [
    {
      "p": "This section moves beyond definitions to explore the specific technical mechanisms that power AirPods. We will examine formal Bluetooth specifications, acoustic physics, sensor-driven logic, and practical diagnostic reasoning."
    }
  ],
  "subsections": [
    {
      "subsection": "Formal Specification: Bluetooth Low Energy (BLE) Profile for Audio",
      "items": [
        {
          "table": [
            [
              "Feature",
              "Bluetooth LE Audio Specification",
              "Relevance to AirPods"
            ],
            [
              "Audio Codec",
              "LC3 (Low Complexity Communication Codec)",
              "Enables high-quality audio at lower bitrates than SBC, extending battery life and maintaining clarity."
            ],
            [
              "Topology",
              "Broadcast Isochronous Stream (BIS) / Connected Isochronous Stream (CIS)",
              "Allows independent routing of audio to each earbud with precise timing synchronization."
            ],
            [
              "Profile",
              "LE Audio (BLE)",
              "Replaces Classic Audio (A2DP) for newer models, offering lower power consumption and bidirectional voice data."
            ],
            [
              "Standard",
              "Bluetooth SIG (Special Interest Group)",
              "Defines the interoperability rules AirPods follow to connect to iPhones and other devices."
            ]
          ]
        },
        {
          "p": "Unlike Classic Bluetooth Audio (A2DP), which streams continuously, LE Audio uses packet switching. This allows AirPods to 'sleep' more aggressively between audio packets, significantly reducing power draw. The LC3 codec is particularly efficient, allowing for higher fidelity at the same bitrate or lower bitrate for the same perceived quality."
        }
      ]
    },
    {
      "subsection": "Mechanism: Beamforming Microphones – Directional Capture Logic",
      "items": [
        {
          "p": "AirPods employ a microphone array (dual beamforming mics) to isolate the user's voice from background noise. This relies on destructive interference."
        },
        {
          "asciiDiagram": [
            "       (Noise Source)",
            "           \\",
            "            \\",
            "             \\",
            "              \\",
            "               \\",
            "   <---(AirPods Earbud)--->",
            "   |  Mic L   |   Mic R  |",
            "   |__________|__________|",
            "        |           |",
            "        \\           /",
            "         \\         /",
            "          \\       /",
            "           \\     /",
            "            Phase",
            "            Shift",
            "               |",
            "           (Signal Processing Unit)",
            "               |",
            "          (Noise Cancelled)"
          ]
        },
        {
          "p": "Logic Flow: 1. The outer microphone picks up a mix of voice and noise. 2. The inner microphone picks up mostly noise (due to proximity to cheek). 3. The digital signal processor (DSP) mathematically inverts the phase of the noise signal from the inner mic. 4. When combined with the outer mic's signal, the noise frequencies cancel out (destructive interference), leaving primarily the voice signal."
        }
      ]
    },
    {
      "subsection": "Adaptive EQ Logic: Dynamic Driver Architecture",
      "items": [
        {
          "p": "Adaptive EQ adjusts the audio output in real-time based on the fit of the earbud. The internal microphones (pointing toward the ear) listen to the sound exiting the ear canal and send feedback to the DSP."
        },
        {
          "ul": [
            "Step 1: AirPods emit a chirp (probe signal) into the ear canal.",
            "Step 2: The inward-facing mic records how that signal reflects off the eardrum.",
            "Step 3: The DSP calculates the frequency response (bass, mids, treble).",
            "Step 4: If the seal is poor (e.g., bass is lost), the EQ boosts low frequencies digitally.",
            "Step 5: The driver plays the corrected signal, ensuring consistent audio quality regardless of ear shape."
          ]
        }
      ]
    },
    {
      "subsection": "Power Management Causal Loop: Proximity Sensor Triggers Sleep/Wake",
      "items": [
        {
          "ul": [
            "Cause A: In-Ear Detection (Optical Sensor)",
            " - Infrared light reflects off skin → High reflectance detected.",
            " - Effect: Microphone switches from 'standby' to 'active'; DSP enables audio stream.",
            "Cause B: Removal from Ear",
            " - Light reflectance drops (detects air or outer ear surface).",
            " - Effect: Audio stream pauses; BT connection enters low-power state (sniff mode).",
            "Cause C: Idle Timeout",
            " - No audio input/output for X minutes.",
            " - Effect: Complete radio shutdown (Deep Sleep) until button press or re-insertion.",
            "Key Mechanism: This is a negative feedback loop. As battery drains, the system becomes more aggressive in entering sleep states to stabilize voltage."
          ]
        }
      ]
    },
    {
      "subsection": "Application Task: Diagnose an Interference Scenario Using Logical Reasoning",
      "items": [
        {
          "p": "Scenario: A user reports that their left AirPod disconnects intermittently when they are walking past a crowded train station, but the right AirPod remains connected. Using the mechanisms learned above, diagnose the likely cause."
        },
        {
          "ul": [
            "Observation: Intermittent disconnection of one device in a crowded RF environment.",
            "Step 1: Check Physical Obstruction (Body Attenuation). The human body absorbs 2.4GHz/5GHz signals. If the phone is in the pocket opposite the disconnecting AirPod (e.g., phone in right pocket, left AirPod disconnecting), signal attenuation is high.",
            "Step 2: Check BLE Interference. Train stations have high interference from WiFi and other Bluetooth devices. LE Audio uses frequency hopping. The left earbud may be hitting a 'bad channel' due to the antenna position relative to the body.",
            "Step 3: Verify Beamforming Logic. If the wind noise triggers the beamforming mics aggressively, the DSP might prioritize noise cancellation over maintaining a stable RF link (power draw conflict).",
            "Conclusion: Likely cause is body shielding combined with high RF noise floor. Solution: Keep phone in the same-side pocket or use a case with the phone exposed to reduce attenuation."
          ]
        }
      ]
    },
    {
      "subsection": "Mini-Check: Comprehensive MCQ Covering Protocols, Mechanisms, and Edge Cases",
      "items": [
        {
          "flip": [
            "Q: Which codec is central to Bluetooth LE Audio (used in newer AirPods) for efficiency?",
            "A: LC3 (Low Complexity Communication Codec).",
            "Hint: Look for the acronym that implies low complexity and is newer than SBC.",
            "Explanation: LC3 allows for lower bitrates while maintaining audio quality, crucial for battery life in small devices."
          ]
        },
        {
          "flip": [
            "Q: How do AirPods isolate voice from background noise using two microphones?",
            "A: By using phase inversion (beamforming) to cancel noise picked up by the inner mic from the outer mic's signal.",
            "Hint: Think about waves interfering and canceling each other out.",
            "Explanation: This is destructive interference. The inner mic samples noise, the DSP inverts the phase, and the mix cancels the noise frequencies."
          ]
        },
        {
          "flip": [
            "Q: What triggers an AirPod to switch from 'active' to 'sleep' mode?",
            "A: The optical proximity sensor detecting removal from the ear.",
            "Hint: It's an optical sensor, not a touch sensor.",
            "Explanation: Removal breaks the infrared light reflection path, signaling the DSP to pause audio and reduce power consumption."
          ]
        },
        {
          "flip": [
            "Q: True or False: Adaptive EQ works by physically changing the shape of the speaker driver.",
            "A: False.",
            "Hint: It's a digital process.",
            "Explanation: Adaptive EQ uses the internal microphone to measure the frequency response in the ear canal and digitally adjusts the EQ curve sent to the driver."
          ]
        },
        {
          "flip": [
            "Q: In a crowded RF environment, why might only one AirPod disconnect?",
            "A: Body shielding (attenuation) or specific antenna positioning causing one earbud to hit interference thresholds.",
            "Hint: The human body absorbs RF signals.",
            "Explanation: The body acts as a barrier. If the phone is on the opposite side of the body from the disconnecting earbud, the signal strength drops significantly."
          ]
        }
      ]
    }
  ]
}]
}

ok, errors, model = validate_lesson(json_payload)
if not ok:
    print(f"Validation FAILED: {errors}")
else:
    print("Validation OK")
