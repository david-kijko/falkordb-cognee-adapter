# Cognee Upgrade Procedure

This adapter is pinned to Cognee 1.0.3 until an explicit contract upgrade is
performed. Treat every Cognee bump as a compatibility migration, not a routine
dependency refresh.

## Required workflow

1. Create a short-lived upgrade branch and activate the project environment:

   ```bash
   source /home/david/.venvs/archie-1.0/bin/activate
   ```

2. Install the candidate Cognee version in that environment, then freeze the live
   Cognee contract:

   ```bash
   make freeze-cognee-contract
   ```

3. Inspect the generated contract diff before changing adapter code:

   ```bash
   git diff tests/fixtures/cognee_1_0_3_contract.json
   ```

   The diff shows signature, abstract-method, import-path, or behavioral surface
   changes that can break the adapter.

4. Run the upgrade contract test:

   ```bash
   pytest tests/test_cognee_upgrade_contract.py
   ```

   This test is expected to fail when Cognee drifts from the frozen fixture. Do
   not mask the failure by loosening the test; use it to identify the exact API
   drift.

5. If the drift is acceptable:

   - bump the Cognee pin in `pyproject.toml`;
   - regenerate the fixture with `make freeze-cognee-contract`;
   - rename the fixture to the new explicit version, for example
     `tests/fixtures/cognee_1_0_X_contract.json`;
   - update tests that point at the old fixture name;
   - run full pytest and lint:

     ```bash
     pytest --require-fixtures -v
     make lint
     ```

   - bump every relevant `SCHEMA_VERSION` constant that describes persisted or
     exported contract shape, including backup/export manifests when their shape
     changes;
   - commit the fixture, dependency, schema-version, and adapter changes together.

6. If the drift is unacceptable, fix adapter signatures and call sites first.
   Re-run `make freeze-cognee-contract`, review the diff again, and only then
   repeat the contract test and full verification.

## Non-negotiables

- Do not update the Cognee pin without checking in the regenerated contract
  fixture.
- Do not bless a contract drift just because tests can be skipped locally.
- Do not touch the live `:6379` FalkorDB instance during upgrade validation; use
  the `docker-compose.test.yml` stack on `127.0.0.1:6380` for fixture-required
  tests.
