import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class DeploymentContractTests(unittest.TestCase):
    def test_docker_image_includes_runtime_modules_and_assets(self):
        dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
        for instruction in (
            "COPY server.py ./server.py",
            "COPY mishu ./mishu",
            "COPY data ./data",
            "COPY web ./web",
        ):
            self.assertIn(instruction, dockerfile)

    def test_dockerignore_does_not_exclude_runtime_modules(self):
        ignored = {
            line.strip()
            for line in (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        }
        self.assertNotIn("mishu", ignored)
        self.assertNotIn("mishu/", ignored)

    def test_compose_uses_least_privilege_defaults(self):
        compose = (ROOT / "compose.yml").read_text(encoding="utf-8")
        for setting in ("read_only: true", "no-new-privileges:true", "cap_drop:", "pids_limit: 128"):
            self.assertIn(setting, compose)


if __name__ == "__main__":
    unittest.main()
