from collections import defaultdict
import logging
import html

def generateActionHTML(htmlPath, templatePath, backupDataSets, excluded):
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
	logging.info("Generating and writing action HTML file to " + htmlPath)
	with open(templatePath, "r") as templateFile:
		template = templateFile.read()

	with open(htmlPath, "w", encoding = "utf-8") as actionHTMLFile:
		# Part 1: Header; Part 2: Table template, used multiple times; Part 3: Footer
		templateParts = template.split("<!-- TEMPLATE -->")
		actionHTMLFile.write(templateParts[0])
		
		for dataSet in backupDataSets:
			# Subdivide in part above and below table data
			tableParts = templateParts[1].split("<!-- ACTIONTABLE -->")
			# Insert name and statistics
			tableHead = tableParts[0].replace("<!-- SOURCENAME -->", html.escape(dataSet.name))
			
			actionHist = defaultdict(int)
			for action in dataSet.actions:
				if ("params" in action) and ("htmlFlags" in action["params"]):
					actionHist[action["type"], action["params"]["htmlFlags"]] += 1
				else:
					actionHist[action["type"], ""] += 1
			# k_v[0][0]: action["type"]; k_v[0][1]: action["params"]["htmlFlags"]
			# k_v[1]: contents of the histogram
			actionOverviewHTML = " | ".join(map(lambda k_v: k_v[0][0] +  ("" if k_v[0][1] == "" else " ("+k_v[0][1]+")")  + ": " + str(k_v[1]), actionHist.items()))
			actionHTMLFile.write(tableHead.replace("<!-- OVERVIEW -->", actionOverviewHTML))

			# Writing this directly is a lot faster than concatenating huge strings
			for action in dataSet.actions:
				if action["type"] not in excluded:
					# Insert zero width space, so that the line breaks at the backslashes
					itemClass = action["type"]
					itemText = action["type"]
					if "htmlFlags" in action["params"]:
						flags = action["params"]["htmlFlags"]
						if flags in excluded:
							continue
						itemClass += "_" + flags
						if flags == "emptyFolder":
							itemText += " (empty directory)"
						elif flags == "inNewDir":
							itemText += " (in new directory)"
						else:
							logging.error("Unknown html flags for action html: " + str(flags))
					# NOTE: we removed a .replace("\\", "\\&#8203;") so copy-pasting paths from the HTML no longer causes problems.
					# This might have unintended side effects as the original reason for this decision is not clear to me
					actionHTMLFile.write("\t\t<tr class=\"" + itemClass + "\"><td class=\"type\">" + itemText
 										 + "</td><td class=\"name\">" + action["params"]["name"] + "</td>\n")
			actionHTMLFile.write(tableParts[1])

		actionHTMLFile.write(templateParts[2])