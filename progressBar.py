import sys
import time

class ProgressBar:
	# stepPrecision: 100 for 1%, 2%, ..., 1000 for 0.1%, 0.2%, ... etc
	def __init__(self, barLength, stepPrecision, totalSteps):
		if totalSteps <= 0:
			raise ValueError("totalSteps must be larger than zero, got " + str(totalSteps))
		self.barLength = barLength
		self.stepPrecision = stepPrecision
		self.totalSteps = totalSteps
		self.lastRelativeProgress = -2

	# count runs from 0 to totalSteps-1; count=0 means that the first step has been done! count=-1 means no steps taken yet
	def update(self, count, suffix=''):
		# Inspired by https://stackoverflow.com/questions/3173320/text-progress-bar-in-the-console
		# Maybe truncate instead of throwing errors, but this is useful for debugging
		if not -1 <= count <= self.totalSteps:
			raise ValueError("count must be between -1 and totalSteps")
		# Make sure we only print if something has changed to avoid massive stdout calls
		relativeProgress = int((count+1)*self.stepPrecision/float(self.totalSteps))
		if (relativeProgress == self.lastRelativeProgress): return
		self.lastRelativeProgress = relativeProgress
		
		filledLength = int(round(self.barLength * (count+1) / float(self.totalSteps)))
		# idea: show more significant digits if  stepPrecision > 1000
		percents = round(100.0 * (count+1) / float(self.totalSteps), 1)
		bar = '=' * filledLength + '.' * (self.barLength - filledLength)
		sys.stdout.write('[%s] %s%%\r' % (bar, percents))
		sys.stdout.flush()
		
if __name__ == '__main__':
	# Test code
	bar = ProgressBar(50, 500, 10000)
	for i in range(1, 10000):
		bar.update(i)
		time.sleep(0.001)