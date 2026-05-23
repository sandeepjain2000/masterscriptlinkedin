Purpose
-------
Combined LinkedIn + Instagram automation: Zlinkedin_suite.py attaches to an
already-open Firefox (Marionette), runs selected tasks in tabs, then closes
the browser when finished.

Instagram profiles to like/comment are in Zlinkedin_suite.py -> IG_TARGET_PROFILES.


Quick start
-----------
1. Double-click Zlinkedin_suite.bat (or BatFiles\zSuite.bat)
   - Starts Firefox with --marionette and opens LinkedIn feed
   - Waits 15s, then runs the Python menu

2. Or manually:
   - Close Firefox completely
   - Start Firefox with Marionette:
       "C:\Program Files\Mozilla Firefox\firefox.exe" --marionette
   - Log in to https://www.linkedin.com (window title must contain "LinkedIn")
     OR https://www.instagram.com ("Instagram" in title — used if LinkedIn is not open)
   - cd to this folder
   - python Zlinkedin_suite.py

3. At the menu, enter:
   5 = Everything (advocate comment, TPO, congratulate, likes, post, Instagram)
   7 = Instagram only
   8 = Fund Raising AI comment (funding required; any startup sector)


Does Firefox need to be open?
-----------------------------
Yes. The script does NOT launch a fresh Selenium profile. It:
  - Finds a Firefox window whose title contains "LinkedIn" (preferred)
  - If LinkedIn is not open, uses a Firefox window whose title contains "Instagram"
  - Attaches via Marionette (--connect-existing)
  - LinkedIn tasks need a LinkedIn window; Instagram-only window runs Task 7 only

Firefox must have marionette.enabled = true OR be started with --marionette.


Files
-----
  Zlinkedin_suite.py     Main script (task menu 1-7)
  Zlinkedin_suite.bat    Start Firefox + run suite
  (AI keys)              Shared pool: ..\nvidia_keys\key*.json (via nvidia_llm.py)
  logs_and_reports\      Per-run logs
  *.db                   SQLite history (in SmallNotFrequent\LinkedIn_Like / LinkedIn_post Working\)


Related launchers (BatFiles\)
-----------------------------
  zIFL.bat   Newer: Instagram liker + LinkedIn poster (separate scripts)
  IFL.bat    Earlier: Instagram liker-comment + 3 LinkedIn scripts (Selenium each)
