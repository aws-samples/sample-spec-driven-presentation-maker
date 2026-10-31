-- Which route, if any, creates an animation effect in PowerPoint for Mac?
--
-- The capture run on 2026-10-31 found that every MsoAnimEffect candidate failed
-- with "main sequence of timeline of slide N doesn't understand the add effect
-- message". PowerPoint.sdef declares "add effect" with a direct parameter of
-- type "sequence", but no class declares responds-to for it. The sdef does,
-- however, declare "effect" as an element of "sequence", so "make new effect"
-- is a second route the oracle never tried, and "add effect" may simply be
-- served by the indexed sequence rather than by "main sequence".
--
-- A first run of this probe reported "effects now on the slide: 2", so at least
-- two routes work. That run's verdicts were unreadable because AppleScript's
-- "return" is a carriage return and the terminal overwrote each line with the
-- next, so this version writes one JSON line per route to a file instead and
-- prints nothing but the path.
--
-- Each route gets its own slide, so the effect count after a route is the
-- evidence for that route alone. The probe closes its presentation without
-- saving after writing the package it needs for offline inspection.
--
-- USAGE
--   osascript /tmp/sdpm-probe/animation-routes.applescript

property kOut : "/tmp/sdpm-probe/routes.jsonl"
property kPackage : "/tmp/sdpm-probe/routes.pptx"

on quoteText(theText)
	set out to ""
	repeat with c in (characters of theText)
		set ch to c as string
		if ch is "\"" then
			set out to out & "\\\""
		else if ch is "\\" then
			set out to out & "\\\\"
		else if ch is (ASCII character 10) then
			set out to out & "\\n"
		else if ch is (ASCII character 13) then
			set out to out & "\\n"
		else
			set out to out & ch
		end if
	end repeat
	return out
end quoteText

on emit(theLine)
	do shell script "printf '%s\\n' " & quoted form of theLine & " >> " & quoted form of kOut
end emit

on record_(routeId, call, slideIndex, ok, detail, effectCount)
	my emit("{\"route\":\"" & routeId & "\",\"call\":\"" & my quoteText(call) & ¬
		"\",\"slideIndex\":" & slideIndex & ",\"ok\":" & ok & ¬
		",\"detail\":\"" & my quoteText(detail) & "\",\"effectsOnSlide\":" & effectCount & "}")
end record_

on newProbeSlide(probe)
	tell application "Microsoft PowerPoint"
		set theSlide to make new slide at end of probe with properties {layout:slide layout blank}
		-- Syntax copied verbatim from the oracle's makeProbeShape, which works
		-- on this build.
		set theShape to make new shape at end of theSlide with properties ¬
			{auto shape type:autoshape rounded rectangle, left position:120, top:120, width:320, height:160}
		set name of theShape to "probe-shape"
	end tell
	return {theSlide, theShape}
end newProbeSlide

on countEffects(theSlide)
	try
		tell application "Microsoft PowerPoint"
			return count of effects of (main sequence of timeline of theSlide)
		end tell
	on error
		return -1
	end try
end countEffects

on run
	do shell script "mkdir -p /tmp/sdpm-probe && : > " & quoted form of kOut & ¬
		" && rm -f " & quoted form of kPackage

	tell application "Microsoft PowerPoint"
		activate
		set appVersion to version as string
		set probe to make new presentation
	end tell
	my emit("{\"record\":\"application\",\"version\":\"" & appVersion & "\"}")

	-- Route A: the oracle's current call, for the record.
	set pair to my newProbeSlide(probe)
	set slideA to item 1 of pair
	set shapeA to item 2 of pair
	tell application "Microsoft PowerPoint" to set indexA to slide index of slideA
	try
		tell application "Microsoft PowerPoint"
			set fx to add effect (main sequence of timeline of slideA) for shapeA ¬
				fx animation type fade trigger on page click
			set detail to animation effect type of fx as string
		end tell
		my record_("A", "add effect (main sequence of timeline of slide)", indexA, "true", detail, my countEffects(slideA))
	on error errText number errNum
		my record_("A", "add effect (main sequence of timeline of slide)", indexA, "false", ((errNum as string) & " " & errText), my countEffects(slideA))
	end try

	-- Route B: make, addressed through "main sequence".
	set pair to my newProbeSlide(probe)
	set slideB to item 1 of pair
	set shapeB to item 2 of pair
	tell application "Microsoft PowerPoint" to set indexB to slide index of slideB
	try
		tell application "Microsoft PowerPoint"
			set fx to make new effect at end of (main sequence of timeline of slideB) ¬
				with properties {shape:shapeB, animation effect type:animation type fade}
			set detail to animation effect type of fx as string
		end tell
		my record_("B", "make new effect at end of (main sequence of timeline of slide)", indexB, "true", detail, my countEffects(slideB))
	on error errText number errNum
		my record_("B", "make new effect at end of (main sequence of timeline of slide)", indexB, "false", ((errNum as string) & " " & errText), my countEffects(slideB))
	end try

	-- Route C: make, addressed through the indexed sequence.
	set pair to my newProbeSlide(probe)
	set slideC to item 1 of pair
	set shapeC to item 2 of pair
	tell application "Microsoft PowerPoint" to set indexC to slide index of slideC
	try
		tell application "Microsoft PowerPoint"
			set fx to make new effect at end of (sequence 1 of timeline of slideC) ¬
				with properties {shape:shapeC, animation effect type:animation type fade}
			set detail to animation effect type of fx as string
		end tell
		my record_("C", "make new effect at end of (sequence 1 of timeline of slide)", indexC, "true", detail, my countEffects(slideC))
	on error errText number errNum
		my record_("C", "make new effect at end of (sequence 1 of timeline of slide)", indexC, "false", ((errNum as string) & " " & errText), my countEffects(slideC))
	end try

	-- Route D: add effect addressed through the indexed sequence.
	set pair to my newProbeSlide(probe)
	set slideD to item 1 of pair
	set shapeD to item 2 of pair
	tell application "Microsoft PowerPoint" to set indexD to slide index of slideD
	try
		tell application "Microsoft PowerPoint"
			set fx to add effect (sequence 1 of timeline of slideD) for shapeD ¬
				fx animation type fade trigger on page click
			set detail to animation effect type of fx as string
		end tell
		my record_("D", "add effect (sequence 1 of timeline of slide)", indexD, "true", detail, my countEffects(slideD))
	on error errText number errNum
		my record_("D", "add effect (sequence 1 of timeline of slide)", indexD, "false", ((errNum as string) & " " & errText), my countEffects(slideD))
	end try

	-- Save the package so the OOXML each working route produced can be read
	-- offline, then discard the working copy.
	try
		tell application "Microsoft PowerPoint"
			save probe in (POSIX file kPackage) as save as Open XML presentation
		end tell
		my emit("{\"record\":\"package\",\"path\":\"" & kPackage & "\",\"saved\":true}")
	on error errText number errNum
		my emit("{\"record\":\"package\",\"saved\":false,\"detail\":\"" & my quoteText((errNum as string) & " " & errText) & "\"}")
	end try

	try
		tell application "Microsoft PowerPoint" to close probe saving no
	end try

	return "wrote " & kOut
end run
