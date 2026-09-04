#! /usr/bin/env python
# -*- encoding: UTF-8 -*-

"""
NAOqi Human Greeter

When a person arrives:
    1. Say "Hi"
    2. Ask "What is your name?"
    3. Listen for their name using Google Speech Recognition
    4. Store the name using the person's NAOqi ID

When that person leaves:
    1. Say "Goodbye <name>"
"""

import qi
import time
import sys
import argparse
import speech_recognition as sr


class HumanGreeter(object):
    """
    Reacts to PeoplePerception arrival/departure events and
    associates spoken names with NAOqi person IDs.
    """

    def __init__(self, app):
        """
        Initialize qi framework, PeoplePerception events,
        text-to-speech, and Google speech recognition.
        """
        super(HumanGreeter, self).__init__()

        app.start()
        self.session = app.session

        # Get ALMemory.
        self.memory = self.session.service("ALMemory")

        # Get the text-to-speech service.
        self.tts = self.session.service("ALTextToSpeech")

        # Store names using the NAOqi person ID as the key.
        self.names = {}

        # Speech recognition object.
        self.recognizer = sr.Recognizer()

        # Use the computer's default microphone.
        self.microphone = sr.Microphone()

        # Subscribe to "person arrived".
        self.arrived_subscriber = self.memory.subscriber(
            "PeoplePerception/JustArrived"
        )
        self.arrived_subscriber.signal.connect(self.on_person_arrived)

        # Subscribe to "person left".
        self.left_subscriber = self.memory.subscriber(
            "PeoplePerception/JustLeft"
        )
        self.left_subscriber.signal.connect(self.on_person_left)

    def recognize_name(self):
        """
        Listen to the microphone and use Google's speech recognition
        to convert the person's answer into text.
        """

        print("Listening for name...")

        try:
            with self.microphone as source:
                # Calibrate for the current ambient noise.
                self.recognizer.adjust_for_ambient_noise(
                    source,
                    duration=0.5
                )

                # Listen for the person's answer.
                audio = self.recognizer.listen(
                    source,
                    timeout=5,
                    phrase_time_limit=5
                )

            print("Recognizing speech...")

            # Use Google Speech Recognition.
            name = self.recognizer.recognize_google(
                audio,
                language="en-US"
            )

            print("Google recognized: " + name)

            return name

        except sr.WaitTimeoutError:
            print("Timed out waiting for the person to speak.")
            return "unknown"

        except sr.UnknownValueError:
            print("Google could not understand the person's speech.")
            return "unknown"

        except sr.RequestError as error:
            print("Google Speech Recognition error: " + str(error))
            return "unknown"

    def on_person_arrived(self, person_id):
        """
        Called when a new person is added to the PeoplePerception
        population.

        JustArrived supplies the person's ID directly.
        """

        print("Person arrived with ID: " + str(person_id))

        # Greet the person.
        self.tts.say("Hi")

        # Ask their name.
        self.tts.say("What is your name")

        # Listen for their response.
        name = self.recognize_name()

        # Store the name associated with this person's ID.
        self.names[person_id] = name

        print(
            "Stored name '" + name +
            "' for person ID " + str(person_id)
        )

    def on_person_left(self, person_id):
        """
        Called when a person is removed from the PeoplePerception
        population.

        JustLeft supplies the person's ID directly.
        """

        print("Person left with ID: " + str(person_id))

        # Look up their name.
        name = self.names.pop(person_id, "unknown")

        # Say goodbye using the stored name.
        self.tts.say("Goodbye " + name)

        print(
            "Said goodbye to '" + name +
            "' (ID " + str(person_id) + ")"
        )

    def run(self):
        """
        Keep the program running until Ctrl+C.
        """
        print("Starting HumanGreeter")

        try:
            while True:
                time.sleep(1)

        except KeyboardInterrupt:
            print("Interrupted by user, stopping HumanGreeter")

            sys.exit(0)


if __name__ == "__main__":

    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--ip",
        type=str,
        default="10.1.65.187",
        help="Robot IP address."
    )

    parser.add_argument(
        "--port",
        type=int,
        default=9559,
        help="Naoqi port number"
    )

    args = parser.parse_args()

    try:
        # Initialize qi framework.
        connection_url = (
            "tcp://" +
            args.ip +
            ":" +
            str(args.port)
        )

        app = qi.Application(
            [
                "HumanGreeter",
                "--qi-url=" + connection_url
            ]
        )

    except RuntimeError:
        print(
            "Can't connect to Naoqi at ip \"" +
            args.ip +
            "\" on port " +
            str(args.port) +
            ".\n"
            "Please check your script arguments. "
            "Run with -h option for help."
        )

        sys.exit(1)

    human_greeter = HumanGreeter(app)
    human_greeter.run()

