{
  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixpkgs-unstable";
  inputs.flake-utils.url = "github:numtide/flake-utils";
  inputs.poetry2nix.url = "github:c0h2r/poetry2nix";

  outputs = { self, nixpkgs, flake-utils, poetry2nix }:
    flake-utils.lib.eachDefaultSystem (system:
      let
        p2n = import poetry2nix { inherit pkgs; };
        overrides = p2n.defaultPoetryOverrides.extend (self: super: {
          multipart = super.multipart.overridePythonAttrs (
            old: {
              buildInputs = (old.buildInputs or [ ]) ++ [ super.setuptools ];
            }
          );
        });

        p_env = p2n.mkPoetryEnv {
          python = pkgs.python3;
          projectDir = self;
          inherit overrides;
        };
        p_app = p2n.mkPoetryApplication {
          python = pkgs.python3;
          projectDir = self;
          inherit overrides;
        };
        pkgs = nixpkgs.legacyPackages.${system};
      in {
        packages = {
          todoapp = p_app;
          default = self.packages.${system}.todoapp;
        };
        devShells.default =
          pkgs.mkShell { packages = [ pkgs.poetry p_env ]; };
      });
}
