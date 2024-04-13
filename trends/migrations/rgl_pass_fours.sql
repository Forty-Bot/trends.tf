UPDATE competition
SET formatid = (SELECT formatid FROM format WHERE format = 'fours')
WHERE league = 'rgl'
	AND formatid = (SELECT formatid FROM format WHERE format = 'other');
