from collections import defaultdict
import logging
import html
from pathlib import Path

from Frontdown.backup_procedures import BackupTree
from Frontdown.basics import ACTION, HTMLFLAG


def generateActionHTML(htmlPath: Path, templatePath: Path, backupTrees: list[BackupTree], excluded: list[ACTION | HTMLFLAG]):
    """
    Generates an HTML file summarizing the actions to be taken.

    Parameters
    ----------
    htmlPath: string
        The target HTML file.
    templatePath: string
        The HTML template where the data will be inserted.
    backupDataSets: array of backupData
        The actual data to be inserted.
    excluded: array of string
        Which actions or HTML flags are to be excluded from the HTML file. Possible choices are:
        copy, hardlink, delete, emptyFolder, inNewDir
    """
    logging.info(f"Generating and writing action HTML file to {htmlPath}")
    with templatePath.open("r") as templateFile:
        template = templateFile.read()

    with htmlPath.open("w", encoding="utf-8") as actionHTMLFile:
        # Part 1: Header; Part 2: Table template, used multiple times; Part 3: Footer
        templateParts = template.split("<!-- TEMPLATE -->")
        actionHTMLFile.write(templateParts[0])

        for backupTree in backupTrees:
            # Subdivide in part above and below table data
            tableParts = templateParts[1].split("<!-- ACTIONTABLE -->")
            # Insert name and statistics
            tableHead = tableParts[0].replace("<!-- SOURCENAME -->", html.escape(backupTree.name))

            # TODO: Make changes to this overview or remove it;
            # possibly add statistics
            actionHist: dict[tuple[ACTION, str], int] = defaultdict(int)
            for action in backupTree.actions:
                if action.htmlFlags != HTMLFLAG.NONE:
                    actionHist[action.type, action.htmlFlags] += 1
                else:
                    actionHist[action.type, ""] += 1
            # k_v[0][0]: action["type"]; k_v[0][1]: action["params"]["htmlFlags"]
            # k_v[1]: contents of the histogram
            actionOverviewHTML = " | ".join(map(lambda k_v: k_v[0][0] + ("" if k_v[0][1] ==
                                            "" else " ("+k_v[0][1]+")") + ": " + str(k_v[1]), actionHist.items()))
            actionHTMLFile.write(tableHead.replace("<!-- OVERVIEW -->", actionOverviewHTML))

            # Writing this directly is a lot faster than concatenating huge strings
            for action in backupTree.actions:
                if action.type in excluded:
                    continue
                if action.htmlFlags in excluded:
                    continue
                itemClass = str(action.type)
                if action.htmlFlags != HTMLFLAG.NONE:
                    itemClass += f"_{action.htmlFlags}"
                # this sets the itemText for HTMLFLAG.NONE and unknown tags
                itemText = str(action.type)
                match action.htmlFlags:
                    case HTMLFLAG.NONE:
                        pass
                    case HTMLFLAG.NEW:
                        itemText = "copy (new)"
                    case HTMLFLAG.IN_NEW_DIR:
                        itemText = "copy (in new directory)"
                    case HTMLFLAG.MODIFIED:
                        itemText = "copy (modified)"
                    case HTMLFLAG.EXISTING_DIR:
                        itemText = "existing directory"
                    case HTMLFLAG.NEW_DIR:
                        itemText = "new directory"
                    case HTMLFLAG.EMPTY_DIR:
                        itemText = "empty directory"
                    case _:
                        logging.error(f"Unknown html flags for action html: {action.htmlFlags}")
                # NOTE: A .replace("\\", "\\&#8203;") was removed here, so copy-pasting paths from the HTML
                # does not cause problems. This was originally used to get line break at the backslashes
                actionHTMLFile.write(f'\t\t<tr class="{itemClass}"><td class="type">{itemText}</td><td class="name">{action.name}</td>\n')
            actionHTMLFile.write(tableParts[1])

        actionHTMLFile.write(templateParts[2])
