import base64
import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts/update-official-theme.py"
SPEC = importlib.util.spec_from_file_location("update_official_theme", SCRIPT)
UPDATER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(UPDATER)


class RegistryUpdateTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.assets = self.root / "assets"
        self.assets.mkdir()
        (self.root / "codex-themer-source.json").write_text(
            json.dumps({"sourceSchemaVersion": 1, "namespace": "stdsuperman", "themes": []}),
            encoding="utf-8",
        )
        (self.root / "featured.json").write_text("[]", encoding="utf-8")

    def tearDown(self):
        self.temporary.cleanup()

    def report(self, version="1.0.0", pack=b"pack-v1", card=b"card-v1"):
        name = "dusk-paper"
        pack_name = f"{name}-{version}.ctpack"
        card_name = f"{name}-{version}-card.webp"
        (self.assets / pack_name).write_bytes(pack)
        (self.assets / card_name).write_bytes(card)
        return {
            "reportSchemaVersion": 1,
            "distributionId": "stdsuperman/dusk-paper",
            "namespace": "stdsuperman",
            "name": name,
            "version": version,
            "displayName": "暮色纸张",
            "description": "克制的深色主题",
            "tags": ["深色"],
            "license": "MIT",
            "minSchemaVersion": 4,
            "releaseTag": f"{name}-v{version}",
            "asset": pack_name,
            "size": len(pack),
            "sha256": hashlib.sha256(pack).hexdigest(),
            "cardAsset": card_name,
            "cardSize": len(card),
            "cardSha256": hashlib.sha256(card).hexdigest(),
            "packContentHash": "a" * 64,
            "publishedAt": "2026-07-22T00:00:00Z",
        }

    def source(self):
        return json.loads((self.root / "codex-themer-source.json").read_text(encoding="utf-8"))

    def test_new_version_is_atomic_sorted_and_exact_retry_is_idempotent(self):
        first = self.report()
        self.assertTrue(UPDATER.apply_report(self.root, first, self.assets, featured=True))
        self.assertFalse(UPDATER.apply_report(self.root, first, self.assets, featured=True))
        self.assertEqual(json.loads((self.root / "featured.json").read_text()), ["stdsuperman/dusk-paper"])

        second = self.report("1.1.0", b"pack-v2", b"card-v2")
        self.assertTrue(UPDATER.apply_report(self.root, second, self.assets))
        versions = self.source()["themes"][0]["versions"]
        self.assertEqual([item["version"] for item in versions], ["1.0.0", "1.1.0"])

    def test_existing_version_pin_and_monotonic_history_cannot_be_rewritten(self):
        first = self.report()
        UPDATER.apply_report(self.root, first, self.assets)

        changed = self.report("1.0.0", b"different", b"card-v1")
        with self.assertRaises(UPDATER.RegistryError):
            UPDATER.apply_report(self.root, changed, self.assets)

        older = self.report("0.9.0", b"older", b"older-card")
        with self.assertRaises(UPDATER.RegistryError):
            UPDATER.apply_report(self.root, older, self.assets)

    def test_namespace_and_release_assets_are_rechecked(self):
        report = self.report()
        report["namespace"] = "someone-else"
        with self.assertRaises(UPDATER.RegistryError):
            UPDATER.apply_report(self.root, report, self.assets)

        report = self.report()
        (self.assets / report["asset"]).write_bytes(b"tampered")
        with self.assertRaises(UPDATER.RegistryError):
            UPDATER.apply_report(self.root, report, self.assets)


class CheckedInRegistryTests(unittest.TestCase):
    def test_checked_in_source_and_featured_are_well_formed(self):
        source = json.loads((REPO_ROOT / "codex-themer-source.json").read_text(encoding="utf-8"))
        featured = json.loads((REPO_ROOT / "featured.json").read_text(encoding="utf-8"))
        UPDATER.validate_source(source)
        known = {f'{source["namespace"]}/{theme["name"]}' for theme in source["themes"]}
        self.assertEqual(len(featured), len(set(featured)))
        self.assertTrue(set(featured).issubset(known))

    def test_private_validator_checkout_uses_ephemeral_read_only_deploy_key(self):
        workflow = (REPO_ROOT / ".github/workflows/publish-official-theme.yml").read_text(
            encoding="utf-8"
        )
        checkout_start = workflow.index("- name: Check out the pinned Codex Themer validator")
        checkout_end = workflow.index("- name: Install Rust 1.95", checkout_start)
        checkout = workflow[checkout_start:checkout_end]
        self.assertIn("repository: STDSuperman/codex-themer", checkout)
        self.assertIn("ref: ${{ inputs.themer_ref }}", checkout)
        self.assertIn("ssh-key: ${{ secrets.THEMER_DEPLOY_KEY }}", checkout)
        self.assertIn("persist-credentials: false", checkout)
        self.assertNotIn("allow-write", checkout)

    def test_ubuntu_validator_installs_tauri_system_dependencies(self):
        workflow = (REPO_ROOT / ".github/workflows/publish-official-theme.yml").read_text(
            encoding="utf-8"
        )
        dependencies_start = workflow.index("- name: Install Linux validator dependencies")
        dependencies_end = workflow.index(
            "- name: Download and identify Release assets", dependencies_start
        )
        bootstrap = workflow[dependencies_start:dependencies_end]
        self.assertIn("sudo apt-get update", bootstrap)
        for dependency in (
            "libwebkit2gtk-4.1-dev",
            "libappindicator3-dev",
            "librsvg2-dev",
            "patchelf",
        ):
            self.assertIn(dependency, bootstrap)

    def test_checked_in_metadata_matches_source_and_signature(self):
        try:
            from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
        except ImportError:
            self.skipTest("cryptography 未安装，只跳过签名复核")
        metadata_bytes = (REPO_ROOT / "metadata/metadata-v1.json").read_bytes()
        metadata = json.loads(metadata_bytes)
        source = json.loads((REPO_ROOT / "codex-themer-source.json").read_text(encoding="utf-8"))
        featured = json.loads((REPO_ROOT / "featured.json").read_text(encoding="utf-8"))
        trusted = json.loads((REPO_ROOT / "trusted-sources.json").read_text(encoding="utf-8"))["sources"]
        self.assertEqual(metadata["officialSource"], source)
        self.assertEqual(metadata["featured"], featured)
        self.assertEqual(metadata["trustedSources"], trusted)
        public = bytes.fromhex((REPO_ROOT / "index-public-key.txt").read_text().strip())
        signature = base64.b64decode((REPO_ROOT / "metadata/metadata-v1.json.sig").read_text().strip(), validate=True)
        Ed25519PublicKey.from_public_bytes(public).verify(signature, metadata_bytes)


if __name__ == "__main__":
    unittest.main()
