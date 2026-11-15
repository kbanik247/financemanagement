import os, tempfile, unittest
from app import app, init_db, summary, account_balances

class FinanceSmokeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(delete=False)
        self.tmp.close()
        os.environ["DATABASE_PATH"] = self.tmp.name
        import app as module
        module.DB_PATH = self.tmp.name
        init_db()
        self.client = app.test_client()
        self.client.post("/register", data={"username":"tester","password":"a-very-long-test-password"})
        with self.client.session_transaction() as sess:
            self.csrf = sess["csrf"]
            self.uid = sess["uid"]

    def tearDown(self):
        os.unlink(self.tmp.name)

    def test_health(self):
        self.assertEqual(self.client.get("/health").json["status"], "ok")

if __name__ == "__main__":
    unittest.main()
