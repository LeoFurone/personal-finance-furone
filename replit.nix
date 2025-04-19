{ pkgs }: {
  deps = [
    pkgs.python310Full
    pkgs.python310Packages.pip
    pkgs.python310Packages.setuptools
    pkgs.python310Packages.wheel
    pkgs.python310Packages.pandas
    pkgs.python310Packages.oauth2client
    pkgs.python310Packages.gspread
    pkgs.python310Packages.flask
  ];
}