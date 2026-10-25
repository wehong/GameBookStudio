"""GameBook Studio 런처를 엽니다.  실행: python launcher.py"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

if sys.version_info < (3, 8):
    sys.exit("Python 3.8 이상이 필요합니다.")

from gbengine.deps import require_pygame  # noqa: E402

require_pygame()

from gbengine.gui.launcher import main  # noqa: E402

main()
