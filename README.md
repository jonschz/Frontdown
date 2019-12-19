# Frontdown

## Overview
This is a fork of Frontdown, the original repository can be found [here](https://github.com/pfirsich/Frontdown).

It is an open source hardlink backup tool/script under the GPLv3 license written in Python 3.5.

Here is a quick overview of the features:

* No proprietary container/archive format - files and folders are simply copied, so you can browse them without extra software
* Versioning with the option of using hardlinks - files that have not changed since the last backup can be hardlinked without requiring extra disk space
* An option to generate reports, review the actions to be taken, then take the actions
* Many different modes of operation, one tool for many applications
* Just do the backup - No background service for fancy scheduling and automation throughout, but just a program that backups my stuff when I want it to and is relatively easy to use
* Cross platform support (alpha)

I'm aware that you have to be at least minimally tech-savvy to use Frontdown, since you have to edit your configuration files yourself and start it on the command line using Python and even though I am already using it for my personal backups, I still suspect some bugs lingering because of non-real world and inbred testing, so that I would doubly advice to be a little knowledgable about Python and computers before using it.

## Usage / Quickstart

1. Make a copy of the file [default.config.json](https://github.com/pfirsich/Frontdown/blob/master/default.config.json), give it a name like `userconfig.json`. Do **not** edit the default file!
1. Adapt the values in the file. The comments should explain the purpose of most values. The default values are set for a versioned hardlink backup as described above.
1. Run `backup.py` with your config file as the only argument.

A more thorough documentation will be worked on as soon if someone else shows genuine interest in this project.

## Contributing / Contact
Will be added soon - for now, just make a bug report or a pull request.
