import threading
import time

LOOK_SCREEN_COMMAND = 'look_right'

POSES = {
    'attend': 'breathe',
    'think': 'look_up_right',
    'glance': 'look_down',
    'screen': LOOK_SCREEN_COMMAND,
    'nod': 'nod_yes',
    'shake': 'nod_no',
}

GLANCE_SECONDS = 0.9
LONG_REPLY_WORDS = 14
YIELD_EARLY_SECONDS = 1.2
NOD_SECONDS = 2.5
SHAKE_SECONDS = 3.0
IDLE_GLANCE_AFTER = 25.0
CLOSING_WORDS = ('glad to be of assistance', 'goodbye', 'have a good day')


class Gaze:
    def __init__(self, send=None):
        self.send = send
        self.start = time.time()
        self.pose = None
        self.plan_id = 0
        self.lock = threading.Lock()
        self.last_activity = time.time()
        self.robot_busy = False

    def _set(self, pose, when, why):
        with self.lock:
            command = POSES[pose]
            changed = pose != self.pose or pose in ('nod', 'shake')
            self.pose = pose
            self.last_activity = time.time()
            t = time.time() - self.start
            print(f'[GAZE {t:7.1f}s] {pose.upper():<6} -> {command:<13} | WHEN: {when} | WHY: {why}',
                  flush=True)
            if changed and self.send is not None:
                try:
                    self.send(command)
                except Exception as exc:
                    print('Head command failed:', exc, flush=True)

    def now(self, pose, when, why):
        with self.lock:
            self.plan_id += 1
        self._set(pose, when, why)

    def plan(self, steps):
        with self.lock:
            self.plan_id += 1
            my_id = self.plan_id
        t0 = time.time()

        def run():
            for delay, pose, when, why in sorted(steps, key=lambda s: s[0]):
                wait = t0 + delay - time.time()
                if wait > 0:
                    time.sleep(wait)
                if self.plan_id != my_id:
                    return
                self._set(pose, when, why)

        threading.Thread(target=run, daemon=True).start()

    def user_started_talking(self):
        if self.pose == 'attend':
            with self.lock:
                self.plan_id += 1
            self.last_activity = time.time()
            return
        self.now('attend', 'user starts talking', 'look at the person talking')

    def user_stopped_talking(self):
        self.robot_busy = True
        self.now('think', 'user finished, robot is thinking', 'shows it heard them and is working on it')

    def not_understood(self):
        self.robot_busy = False
        self.now('attend', 'could not understand', 'hand the turn back to the user')

    def robot_replies(self, speech, gesture, talk_time, start_delay):
        words = len(speech.split())
        start = start_delay
        end = max(talk_time, start + 1.0)
        steps = []

        if gesture == 'look_screen':
            steps.append((start, 'screen', 'talking about the computer', 'look at what it is talking about'))
            steps.append((max(start + 1.5, end - YIELD_EARLY_SECONDS), 'attend', 'last few words',
                          'look back before finishing'))
        elif gesture in ('nod', 'shake'):
            length = NOD_SECONDS if gesture == 'nod' else SHAKE_SECONDS
            why = 'agreeing' if gesture == 'nod' else 'problem is too hard'
            steps.append((start, gesture, 'robot starts talking', why))
            steps.append((min(start + length, max(start + 1.0, end - 0.5)), 'attend', 'gesture done',
                          'back to the user'))
        else:
            steps.append((start, 'attend', 'robot starts talking', 'talk to the user'))
            if words >= LONG_REPLY_WORDS:
                mid = start + 0.45 * (end - start)
                steps.append((mid, 'glance', 'middle of a long reply', 'holds its turn so it is not cut off'))
                steps.append((mid + GLANCE_SECONDS, 'attend', 'after the glance', 'back to the user'))

        steps.append((end, 'attend', 'robot done talking, mic back on', 'tells the user it is their turn'))

        if any(phrase in speech.lower() for phrase in CLOSING_WORDS):
            steps.append((end + 1.5, 'glance', 'conversation over', 'breaks eye contact to end it'))
            steps.append((end + 3.5, 'attend', 'ready for the next person', 'back to neutral'))

        self.plan(steps)
        threading.Timer(end, self._turn_over).start()

    def _turn_over(self):
        self.robot_busy = False
        self.last_activity = time.time()

    def start_idle_glances(self):
        def loop():
            while True:
                time.sleep(1)
                quiet = time.time() - self.last_activity
                if not self.robot_busy and self.pose == 'attend' and quiet >= IDLE_GLANCE_AFTER:
                    self.plan([
                        (0, 'glance', f'nobody talked for {IDLE_GLANCE_AFTER:.0f}s', 'so it does not look frozen'),
                        (1.2, 'attend', 'after the idle glance', 'back to facing the user'),
                    ])
                    self.last_activity = time.time()

        threading.Thread(target=loop, daemon=True).start()
