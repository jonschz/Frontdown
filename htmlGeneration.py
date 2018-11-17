from collections import defaultdict
import logging
import html

def generateActionHTML(htmlPath, templatePath, backupDataSets, excluded_actions):
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
				actionHist[action["type"]] += 1
			actionOverviewHTML = " | ".join(map(lambda k_v: k_v[0] + "(" + str(k_v[1]) + ")", actionHist.items()))
			actionHTMLFile.write(tableHead.replace("<!-- OVERVIEW -->", actionOverviewHTML))

			# Writing this directly is a lot faster than concatenating huge strings
			for action in dataSet.actions:
				if action["type"] not in excluded_actions:
					# Insert zero width space, so that the line breaks at the backslashes
					itemClass = action["type"]
					itemText = action["type"]
					if "htmlFlags" in action["params"]:
						flags = action["params"]["htmlFlags"]
						itemClass += "_" + flags
						if flags == "emptyFolder":
							itemText += " (empty directory)"
						elif flags == "inNewDir":
							itemText += " (in new directory)"
						else:
							logging.error("Unknown html flags for action html: " + str(flags))
					actionHTMLFile.write("\t\t<tr class=\"" + itemClass + "\"><td class=\"type\">" + itemText
										 + "</td><td class=\"name\">" + action["params"]["name"].replace("\\", "\\&#8203;") + "</td>\n")
			actionHTMLFile.write(tableParts[1])

		actionHTMLFile.write(templateParts[2])