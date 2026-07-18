{
  description = "Todoist → Joplin migration tool";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs = { self, nixpkgs, flake-utils }:
    flake-utils.lib.eachDefaultSystem (system:
      let
        pkgs = nixpkgs.legacyPackages.${system};
        pythonEnv = pkgs.python3.withPackages (ps: with ps; [
          todoist-api-python
          requests
        ]);
      in
      {
        devShells.default = pkgs.mkShell {
          buildInputs = [ pythonEnv ];
          shellHook = ''
            echo "Todoist → Joplin migration tool"
            echo "Usage: python todoist_to_jex.py --api-token <token>"
          '';
        };

        packages.default = pkgs.stdenv.mkDerivation {
          pname = "todoist-to-jex";
          version = "1.0.0";
          src = ./.;
          buildInputs = [ pythonEnv ];
          installPhase = ''
            mkdir -p $out/bin $out/lib
            cp todoist_to_jex.py $out/bin/todoist-to-jex
            cp -r src $out/lib/
            chmod +x $out/bin/todoist-to-jex
            patchShebangs $out/bin/todoist-to-jex
            substituteInPlace $out/bin/todoist-to-jex \
              --replace-fail "sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))" \
              "sys.path.insert(0, '$out/lib')"
          '';
        };
      }
    );
}
