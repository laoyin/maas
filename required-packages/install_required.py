

import os


def install_command(file_name):
    with open(file_name, "r") as file:
        for line in file.readline():
            os.popen("sudo apt install {command}".format(command=line))



if __name__ == "main":
    install_command("base")
    install_command("dev")