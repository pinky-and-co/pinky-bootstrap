
  precommit-windows:
    # ADR-0023 pilot gate: hermetic pre-commit hooks must run on the brother's
    # machine (Windows, prek only, no toolchain) — this is the real gate, not the Mac.
    runs-on: windows-latest
    permissions:
      contents: read
    strategy:
      matrix:
        shell: [cmd, pwsh]
    defaults:
      run:
        shell: ${{ matrix.shell }}
    steps:
      - uses: actions/checkout@v4

      - name: Set up Python __PYTHON_VERSION__
        uses: actions/setup-python@v5
        with:
          python-version: "__PYTHON_VERSION__"

      - name: Run mdformat hook
        uses: j178/prek-action@v2
        with:
          extra-args: 'mdformat --all-files'

      - name: Install uv
        uses: astral-sh/setup-uv@v6

      - name: Install dependencies
        run: __INSTALL_CMD__

      - name: Tests
        # Added 2026-08-07 (card pyproject-entry-point-et-ci-windows): the pilot gate had only ever
        # proven the HOOKS run hermetically on Windows, never that the repo's own test suite does.
        # Same install/test commands as the Linux job — a real Windows regression should be a red
        # job, not a silent gap this pilot doesn't look at.
        # `uv run` : cf ci.yml.tpl — un `pytest` nu ne trouve rien depuis que l'install passe par
        # `uv sync --locked` (chantier 0024).
        run: uv run __TESTS_CMD__
