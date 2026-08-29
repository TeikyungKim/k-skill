import argparse
import importlib.util
import pathlib
import unittest

MODULE_PATH = (
    pathlib.Path(__file__).resolve().parents[1]
    / "animal-pharmacy-search"
    / "scripts"
    / "animal_pharmacy_mcp.py"
)
spec = importlib.util.spec_from_file_location("animal_pharmacy_mcp", MODULE_PATH)
animal_pharmacy_mcp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(animal_pharmacy_mcp)


class AnimalPharmacyMcpWrapperTests(unittest.TestCase):
    def test_parse_json_object_requires_object(self):
        self.assertEqual(
            animal_pharmacy_mcp.parse_json_object('{"city":"서울"}', arg_name="--json"),
            {"city": "서울"},
        )
        with self.assertRaises(argparse.ArgumentTypeError):
            animal_pharmacy_mcp.parse_json_object('["서울"]', arg_name="--json")

    def test_parse_kv_pairs_json_decodes_values(self):
        parsed = animal_pharmacy_mcp.parse_kv_pairs(
            ["city=서울", "limit=5", "item_srl=4510"]
        )
        self.assertEqual(parsed, {"city": "서울", "limit": 5, "item_srl": 4510})

    def test_parse_args_merges_json_and_kv_arguments(self):
        args = animal_pharmacy_mcp.parse_args(
            [
                "call",
                "find_animal_pharmacies",
                "--json",
                '{"city":"서울","limit":3}',
                "--arg",
                "limit=5",
            ]
        )
        tool_args = dict(args.json_args or {})
        tool_args.update(animal_pharmacy_mcp.parse_kv_pairs(args.kv_args))
        self.assertEqual(args.command, "call")
        self.assertEqual(args.tool, "find_animal_pharmacies")
        self.assertEqual(tool_args, {"city": "서울", "limit": 5})

    def test_parse_mcp_response_accepts_json_and_sse(self):
        json_response = animal_pharmacy_mcp.parse_mcp_response(
            b'{"jsonrpc":"2.0","id":1,"result":{"ok":true}}',
            "application/json",
        )
        sse_response = animal_pharmacy_mcp.parse_mcp_response(
            b'event: message\ndata: {"jsonrpc":"2.0","id":1,"result":{"ok":true}}\n\n',
            "text/event-stream",
        )
        self.assertEqual(json_response["result"], {"ok": True})
        self.assertEqual(sse_response, json_response)

    def test_parse_mcp_response_rejects_rpc_errors(self):
        with self.assertRaisesRegex(
            animal_pharmacy_mcp.AnimalPharmacyMcpError,
            "keyword must be at least 2 characters",
        ):
            animal_pharmacy_mcp.parse_mcp_response(
                b'{"jsonrpc":"2.0","id":1,"error":{"code":-32602,"message":"keyword must be at least 2 characters"}}',
                "application/json",
            )


if __name__ == "__main__":
    unittest.main()
