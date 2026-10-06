import unittest
from unittest.mock import patch
from companion.actions import perform_action

class ActionTests(unittest.TestCase):
    def test_rejects_arbitrary_command(self):
        result, status = perform_action("powershell -Command anything")
        self.assertEqual(status, 400)
        self.assertFalse(result["ok"])

    def test_rejects_unknown_action(self):
        result, status = perform_action("shutdown")
        self.assertEqual(status, 400)
        self.assertFalse(result["ok"])

    @patch("companion.actions.os.name", "posix")
    def test_windows_only_action_is_rejected_off_windows(self):
        result, status = perform_action("task_manager")
        self.assertEqual(status, 400)
        self.assertFalse(result["ok"])

if __name__ == "__main__":
    unittest.main()
