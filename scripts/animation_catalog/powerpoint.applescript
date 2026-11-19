-- Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
-- SPDX-License-Identifier: MIT-0
--
-- Development-only PowerPoint oracle for the animation/transition catalog.
--
-- WHAT IT IS
--   A scripting-dictionary oracle. It applies every candidate of the eight
--   required PowerPoint enumerations, records what PowerPoint reports back,
--   saves the probe deck as Open XML, and leaves the values the dictionary
--   cannot report to OOXML analysis on the Python side. It drives the
--   AppleScript dictionary only; no VBA is used anywhere.
--
-- IT NEVER RUNS BY ITSELF
--   The run handler refuses to address PowerPoint unless the caller passes the
--   explicit consent argument shown under USAGE, and every PowerPoint
--   terminology block sits behind that check. sdpm's runtime, CLI, MCP
--   servers, tests and CI never pass it, so only a maintainer's deliberate
--   invocation launches PowerPoint (REQ-7.3). Checking this file's syntax with
--   the system AppleScript compiler reads the dictionary out of the
--   application bundle and does not launch the application:
--     osacompile -o /tmp/powerpoint-oracle.scpt \
--       scripts/animation_catalog/powerpoint.applescript
--
-- PREREQUISITES on the workstation that runs it
--   System Settings > Privacy & Security > Automation > (your terminal) >
--     Microsoft PowerPoint = on
--   Microsoft PowerPoint for Mac 16.113.1, with no unsaved work open.
--   The Task 1 Morph spike recorded a -10004 privilege violation ("Not
--   authorized to send Apple events to Microsoft PowerPoint") from the sdpm
--   dashboard sandbox, so this has to run from a shell that holds the
--   Automation grant.
--
-- USAGE (both arguments are required)
--   osascript scripts/animation_catalog/powerpoint.applescript \
--     /absolute/path/to/output-dir --run-powerpoint
--
-- WHAT IT WRITES into the output directory
--   powerpoint-readback.jsonl   one JSON record per candidate: the requested
--                               enumerator name and sdef code, the probe slide
--                               index, what PowerPoint reported back, and how
--                               the value is to be resolved.
--   powerpoint-oracle.pptx      the saved probe deck. Analysed offline by
--                               scripts/animation_catalog/generate.py
--                               --parse-oracle <output directory>, which needs
--                               neither PowerPoint nor this script.
--
-- DIVISION OF LABOUR: dictionary read-back vs OOXML analysis
--   Read back through the dictionary (property is readable per PowerPoint.sdef)
--     EPPEntryEffect         entry effect of slide show transition of <slide>
--     MsoAnimEffect          animation effect type of <effect>
--     MsoAnimDirection       direction of effect parameters of <effect>
--     MsoAnimateByLevel      build by level of effect information of <effect>
--     MsoAnimTextUnitEffect  text unit effect information of effect information
--     MsoAnimType            animation behavior type of <animation behavior>
--   Resolved from the saved package instead (the dictionary exposes no reader)
--     MsoAnimTriggerType     "add effect ... trigger" accepts it, but neither
--                            "effect" nor "timing" exposes a trigger property,
--                            so it is read from p:timing//p:cTn/@nodeType and
--                            the p:cond/@evt start condition.
--     MsoAnimAfterEffect     "after effect information" is read-only in the
--                            dictionary, so the value a GUI author picks is
--                            read from p:timing//p:cTn/@afterEffect.
--     presetID, presetSubtype, motion-path geometry and the extension-namespace
--                            transition attributes are package-only facts in
--                            every case; the Python side parses them.
--   Nothing here promotes anything by itself. A maintainer runs this script,
--   keeps its output as a fixture, and generate.py --write folds that checked-in
--   fixture into the catalog, where each promoted entry names the artefact its
--   values came from.
--
-- WHAT THIS BUILD WILL NOT DO: "add effect"
--   The 2026-10-31 run (kept in tests/fixtures/animations/oracle-16.113.1)
--   probed all 207 EPPEntryEffect candidates successfully and every one of the
--   150 MsoAnimEffect candidates was refused with the same error:
--     main sequence of timeline of slide N of presentation "Presentation1"
--     doesn't understand the "add effect" message.
--   No slide in that package carries a p:timing tree. "add effect" is declared
--   in PowerPoint.sdef but PowerPoint for Mac 16.113.1 does not implement it on
--   "main sequence", so probeAnimations, probeDirections, probeTriggers,
--   probeBuildLevels, probeTextUnits, probeBehaviors and probeAfterEffects -
--   all of which begin by adding an effect - cannot work in this build, and no
--   terminology fix will change that. Do not rewrite them: every animation-side
--   capture has to go through the GUI procedure in
--   scripts/animation_catalog/computer-use.md. Transitions are scriptable here
--   and animations are not, which splits the remaining work by mechanism.

property kRunToken : "--run-powerpoint"
property kProbeShapeName : "sdpmOracleProbe"
-- Baseline effect for the probes that need an existing effect to modify. It is
-- resolved by name against the generated MsoAnimEffect arrays, so a PowerPoint
-- upgrade that renames it fails loudly instead of silently probing nothing.
property kBaselineEffectName : "animation type fly"

on run argv
	set argList to argv as list
	if (count of argList) < 2 then
		error "usage: <absolute output directory> " & kRunToken & " -- both arguments are required; the second is the explicit consent that launches Microsoft PowerPoint"
	end if
	if (item 2 of argList) is not kRunToken then
		error "refusing to address Microsoft PowerPoint: pass " & kRunToken & " as the second argument to confirm that launching it is intended"
	end if
	return my captureCatalog(item 1 of argList)
end run

-- ---------------------------------------------------------------------------
-- Capture
-- ---------------------------------------------------------------------------
on captureCatalog(outDir)
	set readbackPath to outDir & "/powerpoint-readback.jsonl"
	set packagePath to outDir & "/powerpoint-oracle.pptx"
	do shell script "mkdir -p " & quoted form of outDir & " && : > " & quoted form of readbackPath & ¬
		" && rm -f " & quoted form of packagePath

	tell application "Microsoft PowerPoint"
		activate
		set appVersion to version as string
		set probe to make new presentation
	end tell
	my emit(readbackPath, my rec({my kv("record", "application"), ¬
		my kv("application", "Microsoft PowerPoint"), ¬
		my kv("version", appVersion), ¬
		my kv("driver", "scripting dictionary"), ¬
		my kvRaw("usesVisualBasic", "false")}))

	-- Each probe is contained and snapshotted. A capture run is expensive and
	-- partially valuable by nature: on 2026-10-31 one bad term in the fourth
	-- probe threw away 357 candidates that had already been applied, because
	-- the failure propagated out of captureCatalog before savePackage ran and
	-- only a hand save of the still-open deck recovered them. A failing probe
	-- is now a record like any other, the run continues to the next one, the
	-- package is written after every probe, and savePackage always runs.
	repeat with probeName in {"probeTransitions", "probeAnimations", "probeDirections", ¬
		"probeTriggers", "probeBuildLevels", "probeTextUnits", "probeBehaviors", "probeAfterEffects"}
		my runProbe(readbackPath, probe, packagePath, contents of probeName)
	end repeat
	my savePackage(readbackPath, probe, packagePath)
	return readbackPath
end captureCatalog

-- Run one probe, record whatever it does, and keep the run alive. The snapshot
-- after each probe means even a crash inside savePackage leaves the applied
-- candidates on disk.
on runProbe(readbackPath, probe, packagePath, probeName)
	set failure to missing value
	try
		if probeName is "probeTransitions" then
			my probeTransitions(readbackPath, probe)
		else if probeName is "probeAnimations" then
			my probeAnimations(readbackPath, probe)
		else if probeName is "probeDirections" then
			my probeDirections(readbackPath, probe)
		else if probeName is "probeTriggers" then
			my probeTriggers(readbackPath, probe)
		else if probeName is "probeBuildLevels" then
			my probeBuildLevels(readbackPath, probe)
		else if probeName is "probeTextUnits" then
			my probeTextUnits(readbackPath, probe)
		else if probeName is "probeBehaviors" then
			my probeBehaviors(readbackPath, probe)
		else if probeName is "probeAfterEffects" then
			my probeAfterEffects(readbackPath, probe)
		else
			error "unknown probe: " & probeName
		end if
	on error errText number errNum
		set failure to {errText, errNum}
	end try
	my emit(readbackPath, my rec({my kv("record", "probe"), ¬
		my kv("probe", probeName)} & my failed(failure)))
	my saveSnapshot(readbackPath, probe, packagePath, probeName)
end runProbe

-- Write the probe deck out where it stands, so a later failure cannot discard
-- what has already been applied. Contained for the same reason.
on saveSnapshot(readbackPath, probe, packagePath, afterProbe)
	set failure to missing value
	set slideCount to 0
	try
		tell application "Microsoft PowerPoint"
			save probe in (POSIX file packagePath) as save as Open XML presentation
			set slideCount to count of slides of probe
		end tell
	on error errText number errNum
		set failure to {errText, errNum}
	end try
	my emit(readbackPath, my rec({my kv("record", "snapshot"), ¬
		my kv("afterProbe", afterProbe), ¬
		my kv("path", packagePath), ¬
		my kvRaw("slideCount", slideCount as string)} & my failed(failure)))
end saveSnapshot

-- EPPEntryEffect: set on the slide's own transition object and read straight
-- back, then confirmed again after the save/reopen round trip.
on probeTransitions(readbackPath, probe)
	set theConstants to my eppEntryEffectConstants()
	set theNames to my eppEntryEffectNames()
	set theCodes to my eppEntryEffectCodes()
	repeat with i from 1 to (count of theNames)
		set theConstant to item i of theConstants
		set failure to missing value
		set appliedIndex to 0
		set appliedDuration to "null"
		tell application "Microsoft PowerPoint"
			set theSlide to make new slide at end of probe with properties {layout:slide layout blank}
			set slideIndex to slide index of theSlide
			try
				set entry effect of slide show transition of theSlide to theConstant
				set appliedIndex to my valueIndex(theConstants, entry effect of slide show transition of theSlide)
				set appliedDuration to (transition duration of slide show transition of theSlide) as string
			on error errText number errNum
				set failure to {errText, errNum}
			end try
		end tell
		my emit(readbackPath, my rec(my head("transition", "EPPEntryEffect", item i of theNames, ¬
			item i of theCodes, slideIndex) & ¬
			{my applied(theNames, appliedIndex), ¬
				my kvRaw("transitionDurationSeconds", appliedDuration), ¬
				my kv("resolvedBy", "dictionaryReadBack"), ¬
				my kv("ooxmlPath", "p:sld/p:transition")} & my failed(failure)))
	end repeat
end probeTransitions

-- MsoAnimEffect: added to a plain rounded rectangle through the main sequence
-- of the slide's timeline, which is the only sequence the sdef exposes by name.
on probeAnimations(readbackPath, probe)
	set theConstants to my msoAnimEffectConstants()
	set theNames to my msoAnimEffectNames()
	set theCodes to my msoAnimEffectCodes()
	repeat with i from 1 to (count of theNames)
		set theConstant to item i of theConstants
		set failure to missing value
		set appliedIndex to 0
		set appliedDuration to "null"
		set isExit to "null"
		tell application "Microsoft PowerPoint"
			set theSlide to make new slide at end of probe with properties {layout:slide layout blank}
			set slideIndex to slide index of theSlide
			set theShape to my makeProbeShape(theSlide)
			try
				set theEffect to add effect (main sequence of timeline of theSlide) for theShape ¬
					fx theConstant trigger on page click
				set appliedIndex to my valueIndex(theConstants, animation effect type of theEffect)
				set appliedDuration to (duration of timing of theEffect) as string
				set isExit to (exit animation of theEffect) as string
			on error errText number errNum
				set failure to {errText, errNum}
			end try
		end tell
		my emit(readbackPath, my rec(my head("animation", "MsoAnimEffect", item i of theNames, ¬
			item i of theCodes, slideIndex) & ¬
			{my applied(theNames, appliedIndex), ¬
				my kvRaw("durationSeconds", appliedDuration), ¬
				my kvRaw("exitAnimation", isExit), ¬
				my kv("resolvedBy", "dictionaryReadBack"), ¬
				my kv("ooxmlPath", "p:timing//p:cTn/@presetClass, @presetID, @presetSubtype")} & ¬
			my failed(failure)))
	end repeat
end probeAnimations

-- MsoAnimDirection: a direction is a parameter of an existing effect.
on probeDirections(readbackPath, probe)
	set theConstants to my msoAnimDirectionConstants()
	set theNames to my msoAnimDirectionNames()
	set theCodes to my msoAnimDirectionCodes()
	set baseEffect to my baselineEffectConstant()
	repeat with i from 1 to (count of theNames)
		set theConstant to item i of theConstants
		set failure to missing value
		set appliedIndex to 0
		tell application "Microsoft PowerPoint"
			set theSlide to make new slide at end of probe with properties {layout:slide layout blank}
			set slideIndex to slide index of theSlide
			set theShape to my makeProbeShape(theSlide)
			try
				set theEffect to add effect (main sequence of timeline of theSlide) for theShape ¬
					fx baseEffect trigger on page click
				set direction of effect parameters of theEffect to theConstant
				set appliedIndex to my valueIndex(theConstants, direction of effect parameters of theEffect)
			on error errText number errNum
				set failure to {errText, errNum}
			end try
		end tell
		my emit(readbackPath, my rec(my head("direction", "MsoAnimDirection", item i of theNames, ¬
			item i of theCodes, slideIndex) & ¬
			{my applied(theNames, appliedIndex), ¬
				my kv("baselineEffect", kBaselineEffectName), ¬
				my kv("resolvedBy", "dictionaryReadBack"), ¬
				my kv("ooxmlPath", "p:timing//p:cTn/@presetSubtype")} & my failed(failure)))
	end repeat
end probeDirections

-- MsoAnimTriggerType: accepted by "add effect ... trigger", but no readable
-- trigger property exists on "effect" or "timing", so the applied value is
-- resolved from the saved package rather than claimed from a read-back.
on probeTriggers(readbackPath, probe)
	set theConstants to my msoAnimTriggerTypeConstants()
	set theNames to my msoAnimTriggerTypeNames()
	set theCodes to my msoAnimTriggerTypeCodes()
	set baseEffect to my baselineEffectConstant()
	repeat with i from 1 to (count of theNames)
		set theConstant to item i of theConstants
		set failure to missing value
		set accepted to "false"
		tell application "Microsoft PowerPoint"
			set theSlide to make new slide at end of probe with properties {layout:slide layout blank}
			set slideIndex to slide index of theSlide
			set theShape to my makeProbeShape(theSlide)
			try
				set theEffect to add effect (main sequence of timeline of theSlide) for theShape ¬
					fx baseEffect trigger theConstant
				set accepted to "true"
			on error errText number errNum
				set failure to {errText, errNum}
			end try
		end tell
		my emit(readbackPath, my rec(my head("trigger", "MsoAnimTriggerType", item i of theNames, ¬
			item i of theCodes, slideIndex) & ¬
			{my kvRaw("applied", "null"), ¬
				my kvRaw("acceptedByDictionary", accepted), ¬
				my kv("readBack", "notExposedByDictionary"), ¬
				my kv("resolvedBy", "ooxmlParse"), ¬
				my kv("ooxmlPath", "p:timing//p:cTn/@nodeType and p:cond/@evt")} & my failed(failure)))
	end repeat
end probeTriggers

-- MsoAnimateByLevel: passed to "add effect ... level" and read back from the
-- effect's own information record. Needs a shape that actually holds text.
on probeBuildLevels(readbackPath, probe)
	set theConstants to my msoAnimateByLevelConstants()
	set theNames to my msoAnimateByLevelNames()
	set theCodes to my msoAnimateByLevelCodes()
	set baseEffect to my baselineEffectConstant()
	repeat with i from 1 to (count of theNames)
		set theConstant to item i of theConstants
		set failure to missing value
		set appliedIndex to 0
		tell application "Microsoft PowerPoint"
			set theSlide to make new slide at end of probe with properties {layout:slide layout blank}
			set slideIndex to slide index of theSlide
			set theShape to my makeProbeShape(theSlide)
			try
				set content of text range of text frame of theShape to ¬
					"Level one" & return & "Level two" & return & "Level three"
				set theEffect to add effect (main sequence of timeline of theSlide) for theShape ¬
					fx baseEffect level theConstant trigger on page click
				set appliedIndex to my valueIndex(theConstants, build by level of effect information of theEffect)
			on error errText number errNum
				set failure to {errText, errNum}
			end try
		end tell
		my emit(readbackPath, my rec(my head("buildLevel", "MsoAnimateByLevel", item i of theNames, ¬
			item i of theCodes, slideIndex) & ¬
			{my applied(theNames, appliedIndex), ¬
				my kv("resolvedBy", "dictionaryReadBack"), ¬
				my kv("ooxmlPath", "p:timing/p:bldLst/p:bldP/@build or p:bldGraphic")} & my failed(failure)))
	end repeat
end probeBuildLevels

-- MsoAnimTextUnitEffect: applied with the dedicated conversion command.
on probeTextUnits(readbackPath, probe)
	set theConstants to my msoAnimTextUnitEffectConstants()
	set theNames to my msoAnimTextUnitEffectNames()
	set theCodes to my msoAnimTextUnitEffectCodes()
	set baseEffect to my baselineEffectConstant()
	repeat with i from 1 to (count of theNames)
		set theConstant to item i of theConstants
		set failure to missing value
		set appliedIndex to 0
		tell application "Microsoft PowerPoint"
			set theSlide to make new slide at end of probe with properties {layout:slide layout blank}
			set slideIndex to slide index of theSlide
			set theShape to my makeProbeShape(theSlide)
			try
				set content of text range of text frame of theShape to "Text unit probe"
				set theEffect to add effect (main sequence of timeline of theSlide) for theShape ¬
					fx baseEffect trigger on page click
				set theConverted to convert to text unit effect (main sequence of timeline of theSlide) ¬
					Effect theEffect unit theConstant
				set appliedIndex to my valueIndex(theConstants, ¬
					text unit effect information of effect information of theConverted)
			on error errText number errNum
				set failure to {errText, errNum}
			end try
		end tell
		my emit(readbackPath, my rec(my head("textUnit", "MsoAnimTextUnitEffect", item i of theNames, ¬
			item i of theCodes, slideIndex) & ¬
			{my applied(theNames, appliedIndex), ¬
				my kv("resolvedBy", "dictionaryReadBack"), ¬
				my kv("ooxmlPath", "p:timing//p:iterate/@type")} & my failed(failure)))
	end repeat
end probeTextUnits

-- MsoAnimType: the behaviour primitives, added to an existing effect.
on probeBehaviors(readbackPath, probe)
	set theConstants to my msoAnimTypeConstants()
	set theNames to my msoAnimTypeNames()
	set theCodes to my msoAnimTypeCodes()
	set baseEffect to my baselineEffectConstant()
	repeat with i from 1 to (count of theNames)
		set theConstant to item i of theConstants
		set failure to missing value
		set appliedIndex to 0
		tell application "Microsoft PowerPoint"
			set theSlide to make new slide at end of probe with properties {layout:slide layout blank}
			set slideIndex to slide index of theSlide
			set theShape to my makeProbeShape(theSlide)
			try
				set theEffect to add effect (main sequence of timeline of theSlide) for theShape ¬
					fx baseEffect trigger on page click
				set theBehavior to add behavior theEffect type theConstant
				set appliedIndex to my valueIndex(theConstants, animation behavior type of theBehavior)
			on error errText number errNum
				set failure to {errText, errNum}
			end try
		end tell
		my emit(readbackPath, my rec(my head("behavior", "MsoAnimType", item i of theNames, ¬
			item i of theCodes, slideIndex) & ¬
			{my applied(theNames, appliedIndex), ¬
				my kv("resolvedBy", "dictionaryReadBack"), ¬
				my kv("ooxmlPath", "p:timing//p:childTnLst behaviour element")} & my failed(failure)))
	end repeat
end probeBehaviors

-- MsoAnimAfterEffect: read-only in the dictionary ("effect information" has no
-- settable after-effect), so each candidate is recorded as package-resolved and
-- the only read-back is the default PowerPoint reports on a fresh effect.
on probeAfterEffects(readbackPath, probe)
	set theConstants to my msoAnimAfterEffectConstants()
	set theNames to my msoAnimAfterEffectNames()
	set theCodes to my msoAnimAfterEffectCodes()
	set baseEffect to my baselineEffectConstant()
	set failure to missing value
	set defaultIndex to 0
	tell application "Microsoft PowerPoint"
		set theSlide to make new slide at end of probe with properties {layout:slide layout blank}
		set slideIndex to slide index of theSlide
		set theShape to my makeProbeShape(theSlide)
		try
			set theEffect to add effect (main sequence of timeline of theSlide) for theShape ¬
				fx baseEffect trigger on page click
			set defaultIndex to my valueIndex(theConstants, ¬
				after effect information of effect information of theEffect)
		on error errText number errNum
			set failure to {errText, errNum}
		end try
	end tell
	repeat with i from 1 to (count of theNames)
		my emit(readbackPath, my rec(my head("afterEffect", "MsoAnimAfterEffect", item i of theNames, ¬
			item i of theCodes, slideIndex) & ¬
			{my kvRaw("applied", "null"), ¬
				my kvRaw("settableByDictionary", "false"), ¬
				my applied2("reportedDefault", theNames, defaultIndex), ¬
				my kv("readBack", "readOnlyProperty"), ¬
				my kv("resolvedBy", "ooxmlParse"), ¬
				my kv("ooxmlPath", "p:timing//p:cTn/@afterEffect")} & my failed(failure)))
	end repeat
end probeAfterEffects

-- Save as Open XML, reopen, confirm what survived, and hand the package to the
-- Python parser for everything the dictionary cannot report.
on savePackage(readbackPath, probe, packagePath)
	set eppConstants to my eppEntryEffectConstants()
	set eppNames to my eppEntryEffectNames()
	set slideCount to 0
	set failure to missing value
	try
		tell application "Microsoft PowerPoint"
			save probe in (POSIX file packagePath) as save as Open XML presentation
			set slideCount to count of slides of probe
			close probe saving no
			open (POSIX file packagePath)
			set reopened to active presentation
		end tell
		repeat with k from 1 to slideCount
			set rowFailure to missing value
			set appliedIndex to 0
			set effectCount to 0
			try
				tell application "Microsoft PowerPoint"
					set theSlide to slide k of reopened
					set appliedIndex to my valueIndex(eppConstants, ¬
						entry effect of slide show transition of theSlide)
					set effectCount to count of effects of main sequence of timeline of theSlide
				end tell
			on error errText number errNum
				set rowFailure to {errText, errNum}
			end try
			my emit(readbackPath, my rec({my kv("record", "reopened"), ¬
				my kvRaw("slideIndex", k as string), ¬
				my applied2("entryEffect", eppNames, appliedIndex), ¬
				my kvRaw("effectCount", effectCount as string)} & my failed(rowFailure)))
		end repeat
		tell application "Microsoft PowerPoint"
			close reopened saving no
		end tell
	on error errText number errNum
		set failure to {errText, errNum}
	end try
	if failure is not missing value then
		my emit(readbackPath, my rec({my kv("record", "saveFailure"), ¬
			my kv("path", packagePath), ¬
			my kv("note", "the package written by the last snapshot is still on disk and can be analysed as it stands")} & ¬
			my failed(failure)))
	end if
	my emit(readbackPath, my rec({my kv("record", "package"), ¬
		my kv("path", packagePath), ¬
		my kvRaw("slideCount", slideCount as string), ¬
		my kv("parser", "scripts/animation_catalog/generate.py --parse-oracle <output directory>"), ¬
		my kv("note", "presetID, presetSubtype, trigger node types, after-effect values, motion-path geometry and extension-namespace transition attributes are resolved from this package, not from the dictionary")}))
end savePackage

-- ---------------------------------------------------------------------------
-- Candidate constants, named by code rather than by term
-- ---------------------------------------------------------------------------
-- The generated arrays below call enumConstant with twelve characters: the
-- four-character type code of the enumeration, then the enumerator's own eight
-- hexadecimal digits. An Apple Event enumerator is exactly that - a descriptor
-- of the enumeration's type carrying the enumerator's four bytes - and
-- AppleScript's raw constant syntax takes those bytes literally, so
-- "run script" is the one way to build one from a code without writing control
-- characters into this file.
--
-- WHY NOT THE ENUMERATOR TERM ITSELF
--   A bare term inside "using terms from" is ambiguous twice over, and the
--   2026-10-31 capture was lost to the first kind:
--     top, font bold, font italic (MsoAnimDirection) and dim
--     (MsoAnimAfterEffect) are also PowerPoint PROPERTY names, so the compiler
--     resolves them as property references and evaluating one raises
--     "Can't get <class> (-1728)", which aborts the whole array.
--     horizontal and vertical (MsoAnimDirection) compile to constants of a
--     DIFFERENT enumeration - TxOr, text orientation - which is worse: nothing
--     fails, the probe applies the wrong value, and the record names the value
--     that was asked for.
--   Naming every candidate by code removes both classes by construction.
--
-- WHY NOT A RAW «data ...» LITERAL
--   «data pEeF00F60F55» compiles and keeps its type, but its AppleScript class
--   is "data", not "constant": it compares unequal to the value PowerPoint
--   reports back, so valueIndex would find nothing and every record would
--   claim "applied": null. A constant built here compares equal to the term it
--   names, which is what keeps the read-back comparison honest.
on enumConstant(typedCode)
	set theBytes to ""
	repeat with i in {5, 7, 9, 11}
		set theHigh to my hexDigit(character (contents of i) of typedCode)
		set theLow to my hexDigit(character ((contents of i) + 1) of typedCode)
		set theBytes to theBytes & (ASCII character (theHigh * 16 + theLow))
	end repeat
	return run script ("«constant " & (text 1 thru 4 of typedCode) & theBytes & "»")
end enumConstant

on hexDigit(theChar)
	set theDigits to "0123456789ABCDEF"
	repeat with i from 1 to 16
		if character i of theDigits is theChar then return i - 1
	end repeat
	error "the candidate code carries a character that is not a hexadecimal digit: " & theChar
end hexDigit

on makeProbeShape(theSlide)
	tell application "Microsoft PowerPoint"
		set theShape to make new shape at end of theSlide with properties ¬
			{auto shape type:autoshape rounded rectangle, left position:120, top:120, width:320, height:160}
		set name of theShape to kProbeShapeName
		return theShape
	end tell
end makeProbeShape

on baselineEffectConstant()
	set theIndex to my valueIndex(my msoAnimEffectNames(), kBaselineEffectName)
	if theIndex is 0 then
		error "the generated MsoAnimEffect arrays no longer contain " & kBaselineEffectName & ¬
			"; regenerate with scripts/animation_catalog/generate.py --write"
	end if
	return item theIndex of my msoAnimEffectConstants()
end baselineEffectConstant

-- ---------------------------------------------------------------------------
-- Record helpers
-- ---------------------------------------------------------------------------
on head(theRecord, theEnum, theName, theCode, slideIndex)
	return {my kv("record", theRecord), my kv("enum", theEnum), my kv("enumerator", theName), ¬
		my kv("code", theCode), my kvRaw("slideIndex", slideIndex as string)}
end head

on applied(theNames, theIndex)
	return my applied2("applied", theNames, theIndex)
end applied

on applied2(theKey, theNames, theIndex)
	if theIndex is 0 then return my kvRaw(theKey, "null")
	return my kv(theKey, item theIndex of theNames)
end applied2

on failed(failure)
	if failure is missing value then return {my kvRaw("rejected", "false")}
	return {my kvRaw("rejected", "true"), my kv("error", item 1 of failure), ¬
		my kvRaw("errorNumber", (item 2 of failure) as string)}
end failed

on valueIndex(theList, theValue)
	repeat with i from 1 to (count of theList)
		if item i of theList is theValue then return i
	end repeat
	return 0
end valueIndex

on kv(theKey, theText)
	return "\"" & theKey & "\":\"" & my escapeJson(theText as string) & "\""
end kv

on kvRaw(theKey, theLiteral)
	return "\"" & theKey & "\":" & theLiteral
end kvRaw

on rec(theParts)
	set savedDelimiters to AppleScript's text item delimiters
	set AppleScript's text item delimiters to ","
	set theBody to theParts as string
	set AppleScript's text item delimiters to savedDelimiters
	return "{" & theBody & "}"
end rec

on emit(thePath, theLine)
	do shell script "printf '%s\\n' " & quoted form of theLine & " >> " & quoted form of thePath
end emit

on escapeJson(theText)
	set theResult to my replaceText(theText, "\\", "\\\\")
	set theResult to my replaceText(theResult, "\"", "\\\"")
	set theResult to my replaceText(theResult, return, " ")
	set theResult to my replaceText(theResult, linefeed, " ")
	return my replaceText(theResult, tab, " ")
end escapeJson

on replaceText(theText, searchText, replaceWith)
	set savedDelimiters to AppleScript's text item delimiters
	set AppleScript's text item delimiters to searchText
	set parts to text items of theText
	set AppleScript's text item delimiters to replaceWith
	set theResult to parts as string
	set AppleScript's text item delimiters to savedDelimiters
	return theResult
end replaceText

-- >>> BEGIN GENERATED sdef CANDIDATE ARRAYS >>>
-- Generated by scripts/animation_catalog/generate.py --write from the locally
-- installed PowerPoint scripting definition: 435 candidates in 8 enumerations,
-- in sdef document order. Do not edit by hand. --check --require-sdef compares
-- every name and every code in this region against the scripting definition,
-- so a PowerPoint upgrade shows up as a failure rather than as silent drift.
--
-- Each enumeration gets three parallel arrays: the constants, each named by
-- its enumeration type code plus its own enumerator code and built by
-- enumConstant rather than written as a bare AppleScript term, which would be
-- ambiguous against PowerPoint's property names and against other
-- enumerations; their sdef names, for the JSONL records; and their sdef codes,
-- for drift detection.

-- MsoAnimEffect: 150 candidates, type code AnFX
on msoAnimEffectConstants()
	return {my enumConstant("AnFX01020000"), ¬
		my enumConstant("AnFX01020001"), ¬
		my enumConstant("AnFX01020002"), ¬
		my enumConstant("AnFX01020003"), ¬
		my enumConstant("AnFX01020004"), ¬
		my enumConstant("AnFX01020005"), ¬
		my enumConstant("AnFX01020006"), ¬
		my enumConstant("AnFX01020007"), ¬
		my enumConstant("AnFX01020008"), ¬
		my enumConstant("AnFX01020009"), ¬
		my enumConstant("AnFX0102000A"), ¬
		my enumConstant("AnFX0102000B"), ¬
		my enumConstant("AnFX0102000C"), ¬
		my enumConstant("AnFX0102000D"), ¬
		my enumConstant("AnFX0102000E"), ¬
		my enumConstant("AnFX0102000F"), ¬
		my enumConstant("AnFX01020010"), ¬
		my enumConstant("AnFX01020011"), ¬
		my enumConstant("AnFX01020012"), ¬
		my enumConstant("AnFX01020013"), ¬
		my enumConstant("AnFX01020014"), ¬
		my enumConstant("AnFX01020015"), ¬
		my enumConstant("AnFX01020016"), ¬
		my enumConstant("AnFX01020017"), ¬
		my enumConstant("AnFX01020018"), ¬
		my enumConstant("AnFX01020019"), ¬
		my enumConstant("AnFX0102001A"), ¬
		my enumConstant("AnFX0102001B"), ¬
		my enumConstant("AnFX0102001C"), ¬
		my enumConstant("AnFX0102001D"), ¬
		my enumConstant("AnFX0102001E"), ¬
		my enumConstant("AnFX0102001F"), ¬
		my enumConstant("AnFX01020020"), ¬
		my enumConstant("AnFX01020021"), ¬
		my enumConstant("AnFX01020022"), ¬
		my enumConstant("AnFX01020023"), ¬
		my enumConstant("AnFX01020024"), ¬
		my enumConstant("AnFX01020025"), ¬
		my enumConstant("AnFX01020026"), ¬
		my enumConstant("AnFX01020027"), ¬
		my enumConstant("AnFX01020028"), ¬
		my enumConstant("AnFX01020029"), ¬
		my enumConstant("AnFX0102002A"), ¬
		my enumConstant("AnFX0102002B"), ¬
		my enumConstant("AnFX0102002C"), ¬
		my enumConstant("AnFX0102002D"), ¬
		my enumConstant("AnFX0102002E"), ¬
		my enumConstant("AnFX0102002F"), ¬
		my enumConstant("AnFX01020030"), ¬
		my enumConstant("AnFX01020031"), ¬
		my enumConstant("AnFX01020032"), ¬
		my enumConstant("AnFX01020033"), ¬
		my enumConstant("AnFX01020034"), ¬
		my enumConstant("AnFX01020035"), ¬
		my enumConstant("AnFX01020036"), ¬
		my enumConstant("AnFX01020037"), ¬
		my enumConstant("AnFX01020038"), ¬
		my enumConstant("AnFX01020039"), ¬
		my enumConstant("AnFX0102003A"), ¬
		my enumConstant("AnFX0102003B"), ¬
		my enumConstant("AnFX0102003C"), ¬
		my enumConstant("AnFX0102003D"), ¬
		my enumConstant("AnFX0102003E"), ¬
		my enumConstant("AnFX0102003F"), ¬
		my enumConstant("AnFX01020040"), ¬
		my enumConstant("AnFX01020041"), ¬
		my enumConstant("AnFX01020042"), ¬
		my enumConstant("AnFX01020043"), ¬
		my enumConstant("AnFX01020044"), ¬
		my enumConstant("AnFX01020045"), ¬
		my enumConstant("AnFX01020046"), ¬
		my enumConstant("AnFX01020047"), ¬
		my enumConstant("AnFX01020048"), ¬
		my enumConstant("AnFX01020049"), ¬
		my enumConstant("AnFX0102004A"), ¬
		my enumConstant("AnFX0102004B"), ¬
		my enumConstant("AnFX0102004C"), ¬
		my enumConstant("AnFX0102004D"), ¬
		my enumConstant("AnFX0102004E"), ¬
		my enumConstant("AnFX0102004F"), ¬
		my enumConstant("AnFX01020050"), ¬
		my enumConstant("AnFX01020051"), ¬
		my enumConstant("AnFX01020052"), ¬
		my enumConstant("AnFX01020053"), ¬
		my enumConstant("AnFX01020054"), ¬
		my enumConstant("AnFX01020055"), ¬
		my enumConstant("AnFX01020056"), ¬
		my enumConstant("AnFX01020057"), ¬
		my enumConstant("AnFX01020058"), ¬
		my enumConstant("AnFX01020059"), ¬
		my enumConstant("AnFX0102005A"), ¬
		my enumConstant("AnFX0102005B"), ¬
		my enumConstant("AnFX0102005C"), ¬
		my enumConstant("AnFX0102005D"), ¬
		my enumConstant("AnFX0102005E"), ¬
		my enumConstant("AnFX0102005F"), ¬
		my enumConstant("AnFX01020060"), ¬
		my enumConstant("AnFX01020061"), ¬
		my enumConstant("AnFX01020062"), ¬
		my enumConstant("AnFX01020063"), ¬
		my enumConstant("AnFX01020064"), ¬
		my enumConstant("AnFX01020065"), ¬
		my enumConstant("AnFX01020066"), ¬
		my enumConstant("AnFX01020067"), ¬
		my enumConstant("AnFX01020068"), ¬
		my enumConstant("AnFX01020069"), ¬
		my enumConstant("AnFX0102006A"), ¬
		my enumConstant("AnFX0102006B"), ¬
		my enumConstant("AnFX0102006C"), ¬
		my enumConstant("AnFX0102006D"), ¬
		my enumConstant("AnFX0102006E"), ¬
		my enumConstant("AnFX0102006F"), ¬
		my enumConstant("AnFX01020070"), ¬
		my enumConstant("AnFX01020071"), ¬
		my enumConstant("AnFX01020072"), ¬
		my enumConstant("AnFX01020073"), ¬
		my enumConstant("AnFX01020074"), ¬
		my enumConstant("AnFX01020075"), ¬
		my enumConstant("AnFX01020076"), ¬
		my enumConstant("AnFX01020077"), ¬
		my enumConstant("AnFX01020078"), ¬
		my enumConstant("AnFX01020079"), ¬
		my enumConstant("AnFX0102007A"), ¬
		my enumConstant("AnFX0102007B"), ¬
		my enumConstant("AnFX0102007C"), ¬
		my enumConstant("AnFX0102007D"), ¬
		my enumConstant("AnFX0102007E"), ¬
		my enumConstant("AnFX0102007F"), ¬
		my enumConstant("AnFX01020080"), ¬
		my enumConstant("AnFX01020081"), ¬
		my enumConstant("AnFX01020082"), ¬
		my enumConstant("AnFX01020083"), ¬
		my enumConstant("AnFX01020084"), ¬
		my enumConstant("AnFX01020085"), ¬
		my enumConstant("AnFX01020086"), ¬
		my enumConstant("AnFX01020087"), ¬
		my enumConstant("AnFX01020088"), ¬
		my enumConstant("AnFX01020089"), ¬
		my enumConstant("AnFX0102008A"), ¬
		my enumConstant("AnFX0102008B"), ¬
		my enumConstant("AnFX0102008C"), ¬
		my enumConstant("AnFX0102008D"), ¬
		my enumConstant("AnFX0102008E"), ¬
		my enumConstant("AnFX0102008F"), ¬
		my enumConstant("AnFX01020090"), ¬
		my enumConstant("AnFX01020091"), ¬
		my enumConstant("AnFX01020092"), ¬
		my enumConstant("AnFX01020093"), ¬
		my enumConstant("AnFX01020094"), ¬
		my enumConstant("AnFX01020095")}
end msoAnimEffectConstants

on msoAnimEffectNames()
	return {"animation type custom", ¬
		"animation type appear", ¬
		"animation type fly", ¬
		"animation type blinds", ¬
		"animation type box", ¬
		"animation type checkerboard", ¬
		"animation type circle", ¬
		"animation type crawl", ¬
		"animation type diamond", ¬
		"animation type dissolve", ¬
		"animation type fade", ¬
		"animation type flash once", ¬
		"animation type peek", ¬
		"animation type plus", ¬
		"animation type random bars", ¬
		"animation type spiral", ¬
		"animation type split", ¬
		"animation type stretch", ¬
		"animation type strips", ¬
		"animation type swivel", ¬
		"animation type wedge", ¬
		"animation type wheel", ¬
		"animation type wipe", ¬
		"animation type zoom", ¬
		"animation type random effect", ¬
		"animation type boomerang", ¬
		"animation type bounce", ¬
		"animation type color reveal", ¬
		"animation type credits", ¬
		"animation type ease in", ¬
		"animation type float", ¬
		"animation type grow and turn", ¬
		"animation type light speed", ¬
		"animation type pinwheel", ¬
		"animation type rise up", ¬
		"animation type swish", ¬
		"animation type thin line", ¬
		"animation type unfold", ¬
		"animation type whip", ¬
		"animation type ascend", ¬
		"animation type center revolve", ¬
		"animation type faded swivel", ¬
		"animation type descend", ¬
		"animation type sling", ¬
		"animation type spinner", ¬
		"animation type stretchy", ¬
		"animation type zip", ¬
		"animation type arc up", ¬
		"animation type fade zoom", ¬
		"animation type glide", ¬
		"animation type expand", ¬
		"animation type flip", ¬
		"animation type shimmer", ¬
		"animation type fold", ¬
		"animation type change fill color", ¬
		"animation type change font", ¬
		"animation type change font color", ¬
		"animation type change font size", ¬
		"animation type change font style", ¬
		"animation type grow shrink", ¬
		"animation type change line color", ¬
		"animation type spin", ¬
		"animation type transparency", ¬
		"animation type bold flash", ¬
		"animation type blast", ¬
		"animation type bold reveal", ¬
		"animation type brush on color", ¬
		"animation type brush on underline", ¬
		"animation type color blend", ¬
		"animation type color wave", ¬
		"animation type complementary color", ¬
		"animation type complementary color 2", ¬
		"animation type constrasting color", ¬
		"animation type darken", ¬
		"animation type desaturate", ¬
		"animation type flash bulb", ¬
		"animation type flicker", ¬
		"animation type grow with color", ¬
		"animation type lighten", ¬
		"animation type style emphasis", ¬
		"animation type teeter", ¬
		"animation type vertical grow", ¬
		"animation type wave", ¬
		"animation type media play", ¬
		"animation type media pause", ¬
		"animation type media stop", ¬
		"animation type circle path", ¬
		"animation type right triangle path", ¬
		"animation type diamond path", ¬
		"animation type hexagon path", ¬
		"animation type 5 point star path", ¬
		"animation type crescent moon path", ¬
		"animation type square path", ¬
		"animation type trapezoid path", ¬
		"animation type heart path", ¬
		"animation type octagon path", ¬
		"animation type 6 point star path", ¬
		"animation type football path", ¬
		"animation type equal triangle path", ¬
		"animation type parallelogram path", ¬
		"animation type pentagon path", ¬
		"animation type 4 point star path", ¬
		"animation type 8 point star path", ¬
		"animation type teardrop path", ¬
		"animation type pointy star path", ¬
		"animation type curved square path", ¬
		"animation type curved x path", ¬
		"animation type vertical figure 8 path", ¬
		"animation type curvy star path", ¬
		"animation type loop de loop path", ¬
		"animation type buzzsaw path", ¬
		"animation type horizontal figure 8 path", ¬
		"animation type peanut path", ¬
		"animation type figure 8 four path", ¬
		"animation type neutron path", ¬
		"animation type swoosh path", ¬
		"animation type bean path", ¬
		"animation type plus path", ¬
		"animation type inverted triangle path", ¬
		"animation type inverted square path", ¬
		"animation type left path", ¬
		"animation type turn right path", ¬
		"animation type arc down path", ¬
		"animation type zigzag path", ¬
		"animation type s curve 2 path", ¬
		"animation type sine wave path", ¬
		"animation type bounce left path", ¬
		"animation type down path", ¬
		"animation type turn up path", ¬
		"animation type arc up path", ¬
		"animation type heartbeat path", ¬
		"animation type spiral right path", ¬
		"animation type wave path", ¬
		"animation type curvy left path", ¬
		"animation type diagonal down right path", ¬
		"animation type turn down path", ¬
		"animation type arc left path", ¬
		"animation type funnel path", ¬
		"animation type spring path", ¬
		"animation type bounce right path", ¬
		"animation type spiral left path", ¬
		"animation type diagonal up right path", ¬
		"animation type turn up right path", ¬
		"animation type arc right path", ¬
		"animation type s curve 1 path", ¬
		"animation type decaying wave path", ¬
		"animation type curvy right path", ¬
		"animation type stairs down path", ¬
		"animation type up path", ¬
		"animation type right path"}
end msoAnimEffectNames

on msoAnimEffectCodes()
	return {"0x01020000", ¬
		"0x01020001", ¬
		"0x01020002", ¬
		"0x01020003", ¬
		"0x01020004", ¬
		"0x01020005", ¬
		"0x01020006", ¬
		"0x01020007", ¬
		"0x01020008", ¬
		"0x01020009", ¬
		"0x0102000a", ¬
		"0x0102000b", ¬
		"0x0102000c", ¬
		"0x0102000d", ¬
		"0x0102000e", ¬
		"0x0102000f", ¬
		"0x01020010", ¬
		"0x01020011", ¬
		"0x01020012", ¬
		"0x01020013", ¬
		"0x01020014", ¬
		"0x01020015", ¬
		"0x01020016", ¬
		"0x01020017", ¬
		"0x01020018", ¬
		"0x01020019", ¬
		"0x0102001a", ¬
		"0x0102001b", ¬
		"0x0102001c", ¬
		"0x0102001d", ¬
		"0x0102001e", ¬
		"0x0102001f", ¬
		"0x01020020", ¬
		"0x01020021", ¬
		"0x01020022", ¬
		"0x01020023", ¬
		"0x01020024", ¬
		"0x01020025", ¬
		"0x01020026", ¬
		"0x01020027", ¬
		"0x01020028", ¬
		"0x01020029", ¬
		"0x0102002a", ¬
		"0x0102002b", ¬
		"0x0102002c", ¬
		"0x0102002d", ¬
		"0x0102002e", ¬
		"0x0102002f", ¬
		"0x01020030", ¬
		"0x01020031", ¬
		"0x01020032", ¬
		"0x01020033", ¬
		"0x01020034", ¬
		"0x01020035", ¬
		"0x01020036", ¬
		"0x01020037", ¬
		"0x01020038", ¬
		"0x01020039", ¬
		"0x0102003a", ¬
		"0x0102003b", ¬
		"0x0102003c", ¬
		"0x0102003d", ¬
		"0x0102003e", ¬
		"0x0102003f", ¬
		"0x01020040", ¬
		"0x01020041", ¬
		"0x01020042", ¬
		"0x01020043", ¬
		"0x01020044", ¬
		"0x01020045", ¬
		"0x01020046", ¬
		"0x01020047", ¬
		"0x01020048", ¬
		"0x01020049", ¬
		"0x0102004a", ¬
		"0x0102004b", ¬
		"0x0102004c", ¬
		"0x0102004d", ¬
		"0x0102004e", ¬
		"0x0102004f", ¬
		"0x01020050", ¬
		"0x01020051", ¬
		"0x01020052", ¬
		"0x01020053", ¬
		"0x01020054", ¬
		"0x01020055", ¬
		"0x01020056", ¬
		"0x01020057", ¬
		"0x01020058", ¬
		"0x01020059", ¬
		"0x0102005a", ¬
		"0x0102005b", ¬
		"0x0102005c", ¬
		"0x0102005d", ¬
		"0x0102005e", ¬
		"0x0102005f", ¬
		"0x01020060", ¬
		"0x01020061", ¬
		"0x01020062", ¬
		"0x01020063", ¬
		"0x01020064", ¬
		"0x01020065", ¬
		"0x01020066", ¬
		"0x01020067", ¬
		"0x01020068", ¬
		"0x01020069", ¬
		"0x0102006a", ¬
		"0x0102006b", ¬
		"0x0102006c", ¬
		"0x0102006d", ¬
		"0x0102006e", ¬
		"0x0102006f", ¬
		"0x01020070", ¬
		"0x01020071", ¬
		"0x01020072", ¬
		"0x01020073", ¬
		"0x01020074", ¬
		"0x01020075", ¬
		"0x01020076", ¬
		"0x01020077", ¬
		"0x01020078", ¬
		"0x01020079", ¬
		"0x0102007a", ¬
		"0x0102007b", ¬
		"0x0102007c", ¬
		"0x0102007d", ¬
		"0x0102007e", ¬
		"0x0102007f", ¬
		"0x01020080", ¬
		"0x01020081", ¬
		"0x01020082", ¬
		"0x01020083", ¬
		"0x01020084", ¬
		"0x01020085", ¬
		"0x01020086", ¬
		"0x01020087", ¬
		"0x01020088", ¬
		"0x01020089", ¬
		"0x0102008a", ¬
		"0x0102008b", ¬
		"0x0102008c", ¬
		"0x0102008d", ¬
		"0x0102008e", ¬
		"0x0102008f", ¬
		"0x01020090", ¬
		"0x01020091", ¬
		"0x01020092", ¬
		"0x01020093", ¬
		"0x01020094", ¬
		"0x01020095"}
end msoAnimEffectCodes

-- MsoAnimDirection: 45 candidates, type code AnDi
on msoAnimDirectionConstants()
	return {my enumConstant("AnDi00F90000"), ¬
		my enumConstant("AnDi00F90001"), ¬
		my enumConstant("AnDi00F90002"), ¬
		my enumConstant("AnDi00F90003"), ¬
		my enumConstant("AnDi00F90004"), ¬
		my enumConstant("AnDi00F90005"), ¬
		my enumConstant("AnDi00F90006"), ¬
		my enumConstant("AnDi00F90007"), ¬
		my enumConstant("AnDi00F90008"), ¬
		my enumConstant("AnDi00F90009"), ¬
		my enumConstant("AnDi00F9000A"), ¬
		my enumConstant("AnDi00F9000B"), ¬
		my enumConstant("AnDi00F9000C"), ¬
		my enumConstant("AnDi00F9000D"), ¬
		my enumConstant("AnDi00F9000E"), ¬
		my enumConstant("AnDi00F9000F"), ¬
		my enumConstant("AnDi00F90010"), ¬
		my enumConstant("AnDi00F90011"), ¬
		my enumConstant("AnDi00F90012"), ¬
		my enumConstant("AnDi00F90013"), ¬
		my enumConstant("AnDi00F90014"), ¬
		my enumConstant("AnDi00F90015"), ¬
		my enumConstant("AnDi00F90016"), ¬
		my enumConstant("AnDi00F90017"), ¬
		my enumConstant("AnDi00F90018"), ¬
		my enumConstant("AnDi00F90019"), ¬
		my enumConstant("AnDi00F9001A"), ¬
		my enumConstant("AnDi00F9001B"), ¬
		my enumConstant("AnDi00F9001C"), ¬
		my enumConstant("AnDi00F9001D"), ¬
		my enumConstant("AnDi00F9001E"), ¬
		my enumConstant("AnDi00F9001F"), ¬
		my enumConstant("AnDi00F90020"), ¬
		my enumConstant("AnDi00F90021"), ¬
		my enumConstant("AnDi00F90022"), ¬
		my enumConstant("AnDi00F90023"), ¬
		my enumConstant("AnDi00F90024"), ¬
		my enumConstant("AnDi00F90025"), ¬
		my enumConstant("AnDi00F90026"), ¬
		my enumConstant("AnDi00F90027"), ¬
		my enumConstant("AnDi00F90028"), ¬
		my enumConstant("AnDi00F90029"), ¬
		my enumConstant("AnDi00F9002A"), ¬
		my enumConstant("AnDi00F9002B"), ¬
		my enumConstant("AnDi00F9002C")}
end msoAnimDirectionConstants

on msoAnimDirectionNames()
	return {"no direction", ¬
		"up", ¬
		"right", ¬
		"down", ¬
		"left", ¬
		"ordinal mask", ¬
		"up left", ¬
		"up right", ¬
		"down right", ¬
		"down left", ¬
		"top", ¬
		"bottom", ¬
		"top left", ¬
		"top right", ¬
		"bottom right", ¬
		"bottom left", ¬
		"horizontal", ¬
		"vertical", ¬
		"across", ¬
		"inward", ¬
		"out", ¬
		"clockwise", ¬
		"counterclockwise", ¬
		"horizontal in", ¬
		"horizontal out", ¬
		"vertical in", ¬
		"vertical out", ¬
		"slightly", ¬
		"center", ¬
		"in slightly", ¬
		"in center", ¬
		"in bottom", ¬
		"out slightly", ¬
		"out center", ¬
		"out bottom", ¬
		"font bold", ¬
		"font italic", ¬
		"font underline", ¬
		"font strikethrough", ¬
		"font shadow", ¬
		"font all caps", ¬
		"instant", ¬
		"gradual", ¬
		"cycle clockwise", ¬
		"cycle counterclockwise"}
end msoAnimDirectionNames

on msoAnimDirectionCodes()
	return {"0x00f90000", ¬
		"0x00f90001", ¬
		"0x00f90002", ¬
		"0x00f90003", ¬
		"0x00f90004", ¬
		"0x00f90005", ¬
		"0x00f90006", ¬
		"0x00f90007", ¬
		"0x00f90008", ¬
		"0x00f90009", ¬
		"0x00f9000a", ¬
		"0x00f9000b", ¬
		"0x00f9000c", ¬
		"0x00f9000d", ¬
		"0x00f9000e", ¬
		"0x00f9000f", ¬
		"0x00f90010", ¬
		"0x00f90011", ¬
		"0x00f90012", ¬
		"0x00f90013", ¬
		"0x00f90014", ¬
		"0x00f90015", ¬
		"0x00f90016", ¬
		"0x00f90017", ¬
		"0x00f90018", ¬
		"0x00f90019", ¬
		"0x00f9001a", ¬
		"0x00f9001b", ¬
		"0x00f9001c", ¬
		"0x00f9001d", ¬
		"0x00f9001e", ¬
		"0x00f9001f", ¬
		"0x00f90020", ¬
		"0x00f90021", ¬
		"0x00f90022", ¬
		"0x00f90023", ¬
		"0x00f90024", ¬
		"0x00f90025", ¬
		"0x00f90026", ¬
		"0x00f90027", ¬
		"0x00f90028", ¬
		"0x00f90029", ¬
		"0x00f9002a", ¬
		"0x00f9002b", ¬
		"0x00f9002c"}
end msoAnimDirectionCodes

-- MsoAnimTriggerType: 5 candidates, type code AnTr
on msoAnimTriggerTypeConstants()
	return {my enumConstant("AnTr01000000"), ¬
		my enumConstant("AnTr01000001"), ¬
		my enumConstant("AnTr01000002"), ¬
		my enumConstant("AnTr01000003"), ¬
		my enumConstant("AnTr01000004")}
end msoAnimTriggerTypeConstants

on msoAnimTriggerTypeNames()
	return {"no trigger", ¬
		"on page click", ¬
		"with previous", ¬
		"after previous", ¬
		"on shape click"}
end msoAnimTriggerTypeNames

on msoAnimTriggerTypeCodes()
	return {"0x01000000", ¬
		"0x01000001", ¬
		"0x01000002", ¬
		"0x01000003", ¬
		"0x01000004"}
end msoAnimTriggerTypeCodes

-- MsoAnimateByLevel: 12 candidates, type code AnLv
on msoAnimateByLevelConstants()
	return {my enumConstant("AnLv01010000"), ¬
		my enumConstant("AnLv01010001"), ¬
		my enumConstant("AnLv01010002"), ¬
		my enumConstant("AnLv01010003"), ¬
		my enumConstant("AnLv01010004"), ¬
		my enumConstant("AnLv01010005"), ¬
		my enumConstant("AnLv01010006"), ¬
		my enumConstant("AnLv01010007"), ¬
		my enumConstant("AnLv01010008"), ¬
		my enumConstant("AnLv01010009"), ¬
		my enumConstant("AnLv0101000A"), ¬
		my enumConstant("AnLv0101000B")}
end msoAnimateByLevelConstants

on msoAnimateByLevelNames()
	return {"text by no levels", ¬
		"text by all levels", ¬
		"text by first level", ¬
		"text by second level", ¬
		"text by third level", ¬
		"text by fourth level", ¬
		"text by fifth level", ¬
		"chart all at once", ¬
		"chart by category", ¬
		"chart by ctageory elements", ¬
		"chart by series", ¬
		"chart by series elements"}
end msoAnimateByLevelNames

on msoAnimateByLevelCodes()
	return {"0x01010000", ¬
		"0x01010001", ¬
		"0x01010002", ¬
		"0x01010003", ¬
		"0x01010004", ¬
		"0x01010005", ¬
		"0x01010006", ¬
		"0x01010007", ¬
		"0x01010008", ¬
		"0x01010009", ¬
		"0x0101000a", ¬
		"0x0101000b"}
end msoAnimateByLevelCodes

-- MsoAnimTextUnitEffect: 3 candidates, type code AnTU
on msoAnimTextUnitEffectConstants()
	return {my enumConstant("AnTU00FE0000"), ¬
		my enumConstant("AnTU00FE0001"), ¬
		my enumConstant("AnTU00FE0002")}
end msoAnimTextUnitEffectConstants

on msoAnimTextUnitEffectNames()
	return {"by paragraph", ¬
		"by character", ¬
		"by word"}
end msoAnimTextUnitEffectNames

on msoAnimTextUnitEffectCodes()
	return {"0x00fe0000", ¬
		"0x00fe0001", ¬
		"0x00fe0002"}
end msoAnimTextUnitEffectCodes

-- MsoAnimAfterEffect: 4 candidates, type code AnAE
on msoAnimAfterEffectConstants()
	return {my enumConstant("AnAE00FF0000"), ¬
		my enumConstant("AnAE00FF0001"), ¬
		my enumConstant("AnAE00FF0002"), ¬
		my enumConstant("AnAE00FF0003")}
end msoAnimAfterEffectConstants

on msoAnimAfterEffectNames()
	return {"no after effect", ¬
		"dim", ¬
		"hide", ¬
		"hide on next click"}
end msoAnimAfterEffectNames

on msoAnimAfterEffectCodes()
	return {"0x00ff0000", ¬
		"0x00ff0001", ¬
		"0x00ff0002", ¬
		"0x00ff0003"}
end msoAnimAfterEffectCodes

-- MsoAnimType: 9 candidates, type code AnTy
on msoAnimTypeConstants()
	return {my enumConstant("AnTy01030000"), ¬
		my enumConstant("AnTy01030001"), ¬
		my enumConstant("AnTy01030002"), ¬
		my enumConstant("AnTy01030003"), ¬
		my enumConstant("AnTy01030004"), ¬
		my enumConstant("AnTy01030005"), ¬
		my enumConstant("AnTy01030006"), ¬
		my enumConstant("AnTy01030007"), ¬
		my enumConstant("AnTy01030008")}
end msoAnimTypeConstants

on msoAnimTypeNames()
	return {"animation type none", ¬
		"animation type motion", ¬
		"animation type color", ¬
		"animation type scale", ¬
		"animation type rotation", ¬
		"animation type property", ¬
		"animation type command", ¬
		"animation type filter", ¬
		"animation type set"}
end msoAnimTypeNames

on msoAnimTypeCodes()
	return {"0x01030000", ¬
		"0x01030001", ¬
		"0x01030002", ¬
		"0x01030003", ¬
		"0x01030004", ¬
		"0x01030005", ¬
		"0x01030006", ¬
		"0x01030007", ¬
		"0x01030008"}
end msoAnimTypeCodes

-- EPPEntryEffect: 207 candidates, type code pEeF
on eppEntryEffectConstants()
	return {my enumConstant("pEeF00F60F6E"), ¬
		my enumConstant("pEeF00F60F6F"), ¬
		my enumConstant("pEeF00F60F04"), ¬
		my enumConstant("pEeF00F60301"), ¬
		my enumConstant("pEeF00F60302"), ¬
		my enumConstant("pEeF00F60F55"), ¬
		my enumConstant("pEeF00F60C02"), ¬
		my enumConstant("pEeF00F60F52"), ¬
		my enumConstant("pEeF00F60C01"), ¬
		my enumConstant("pEeF00F60F54"), ¬
		my enumConstant("pEeF00F60F53"), ¬
		my enumConstant("pEeF00F60401"), ¬
		my enumConstant("pEeF00F60402"), ¬
		my enumConstant("pEeF00F60F05"), ¬
		my enumConstant("pEeF00F60D17"), ¬
		my enumConstant("pEeF00F60D1B"), ¬
		my enumConstant("pEeF00F60D18"), ¬
		my enumConstant("pEeF00F60D1A"), ¬
		my enumConstant("pEeF00F60D19"), ¬
		my enumConstant("pEeF00F60F67"), ¬
		my enumConstant("pEeF00F60F07"), ¬
		my enumConstant("pEeF00F60F08"), ¬
		my enumConstant("pEeF00F60F2A"), ¬
		my enumConstant("pEeF00F60F2B"), ¬
		my enumConstant("pEeF00F60504"), ¬
		my enumConstant("pEeF00F60507"), ¬
		my enumConstant("pEeF00F60505"), ¬
		my enumConstant("pEeF00F60501"), ¬
		my enumConstant("pEeF00F60508"), ¬
		my enumConstant("pEeF00F60506"), ¬
		my enumConstant("pEeF00F60503"), ¬
		my enumConstant("pEeF00F60502"), ¬
		my enumConstant("pEeF00F60D10"), ¬
		my enumConstant("pEeF00F60D0D"), ¬
		my enumConstant("pEeF00F60D0F"), ¬
		my enumConstant("pEeF00F60D0E"), ¬
		my enumConstant("pEeF00F60F4D"), ¬
		my enumConstant("pEeF00F60F4A"), ¬
		my enumConstant("pEeF00F60F4B"), ¬
		my enumConstant("pEeF00F60F4C"), ¬
		my enumConstant("pEeF00F60F62"), ¬
		my enumConstant("pEeF00F60102"), ¬
		my enumConstant("pEeF00F60101"), ¬
		my enumConstant("pEeF00F60F06"), ¬
		my enumConstant("pEeF00F60601"), ¬
		my enumConstant("pEeF00F60F2D"), ¬
		my enumConstant("pEeF00F60F2C"), ¬
		my enumConstant("pEeF00F60F60"), ¬
		my enumConstant("pEeF00F60F61"), ¬
		my enumConstant("pEeF00F60701"), ¬
		my enumConstant("pEeF00F60D24"), ¬
		my enumConstant("pEeF00F60D25"), ¬
		my enumConstant("pEeF00F60D21"), ¬
		my enumConstant("pEeF00F60D1E"), ¬
		my enumConstant("pEeF00F60D20"), ¬
		my enumConstant("pEeF00F60D22"), ¬
		my enumConstant("pEeF00F60D23"), ¬
		my enumConstant("pEeF00F60D1F"), ¬
		my enumConstant("pEeF00F60F09"), ¬
		my enumConstant("pEeF00F60F09"), ¬
		my enumConstant("pEeF00F60F5E"), ¬
		my enumConstant("pEeF00F60F5F"), ¬
		my enumConstant("pEeF00F60F3B"), ¬
		my enumConstant("pEeF00F60F3C"), ¬
		my enumConstant("pEeF00F60F01"), ¬
		my enumConstant("pEeF00F60F02"), ¬
		my enumConstant("pEeF00F60F03"), ¬
		my enumConstant("pEeF00F60F45"), ¬
		my enumConstant("pEeF00F60F44"), ¬
		my enumConstant("pEeF00F60F41"), ¬
		my enumConstant("pEeF00F60F42"), ¬
		my enumConstant("pEeF00F60F43"), ¬
		my enumConstant("pEeF00F60D07"), ¬
		my enumConstant("pEeF00F60D08"), ¬
		my enumConstant("pEeF00F60D04"), ¬
		my enumConstant("pEeF00F60D01"), ¬
		my enumConstant("pEeF00F60D03"), ¬
		my enumConstant("pEeF00F60D05"), ¬
		my enumConstant("pEeF00F60D06"), ¬
		my enumConstant("pEeF00F60D02"), ¬
		my enumConstant("pEeF00F60F34"), ¬
		my enumConstant("pEeF00F60F32"), ¬
		my enumConstant("pEeF00F60F35"), ¬
		my enumConstant("pEeF00F60F33"), ¬
		my enumConstant("pEeF00F60F66"), ¬
		my enumConstant("pEeF00F60F28"), ¬
		my enumConstant("pEeF00F60F29"), ¬
		my enumConstant("pEeF00F60F23"), ¬
		my enumConstant("pEeF00F60F20"), ¬
		my enumConstant("pEeF00F60F22"), ¬
		my enumConstant("pEeF00F60F21"), ¬
		my enumConstant("pEeF00F60F27"), ¬
		my enumConstant("pEeF00F60F24"), ¬
		my enumConstant("pEeF00F60F26"), ¬
		my enumConstant("pEeF00F60F25"), ¬
		my enumConstant("pEeF00F60F3A"), ¬
		my enumConstant("pEeF00F60F72"), ¬
		my enumConstant("pEeF00F60F73"), ¬
		my enumConstant("pEeF00F60F74"), ¬
		my enumConstant("pEeF00F60F0A"), ¬
		my enumConstant("pEeF00F60000"), ¬
		my enumConstant("pEeF00F60F59"), ¬
		my enumConstant("pEeF00F60F56"), ¬
		my enumConstant("pEeF00F60F58"), ¬
		my enumConstant("pEeF00F60F57"), ¬
		my enumConstant("pEeF00F60F70"), ¬
		my enumConstant("pEeF00F60F71"), ¬
		my enumConstant("pEeF00F60F6C"), ¬
		my enumConstant("pEeF00F60F6D"), ¬
		my enumConstant("pEeF00F60F6A"), ¬
		my enumConstant("pEeF00F60F6B"), ¬
		my enumConstant("pEeF00F60F5D"), ¬
		my enumConstant("pEeF00F60F5A"), ¬
		my enumConstant("pEeF00F60F5C"), ¬
		my enumConstant("pEeF00F60F5B"), ¬
		my enumConstant("pEeF00F60D0A"), ¬
		my enumConstant("pEeF00F60D09"), ¬
		my enumConstant("pEeF00F60D0B"), ¬
		my enumConstant("pEeF00F60D0C"), ¬
		my enumConstant("pEeF00F60F68"), ¬
		my enumConstant("pEeF00F60F69"), ¬
		my enumConstant("pEeF00F60F0B"), ¬
		my enumConstant("pEeF00F60F65"), ¬
		my enumConstant("pEeF00F60F0C"), ¬
		my enumConstant("pEeF00F60F0D"), ¬
		my enumConstant("pEeF00F60F0E"), ¬
		my enumConstant("pEeF00F60F0F"), ¬
		my enumConstant("pEeF00F60901"), ¬
		my enumConstant("pEeF00F60902"), ¬
		my enumConstant("pEeF00F60201"), ¬
		my enumConstant("pEeF00F60F38"), ¬
		my enumConstant("pEeF00F60F39"), ¬
		my enumConstant("pEeF00F60F36"), ¬
		my enumConstant("pEeF00F60F37"), ¬
		my enumConstant("pEeF00F60F1B"), ¬
		my enumConstant("pEeF00F60F1E"), ¬
		my enumConstant("pEeF00F60F1D"), ¬
		my enumConstant("pEeF00F60F1F"), ¬
		my enumConstant("pEeF00F60F1C"), ¬
		my enumConstant("pEeF00F60F51"), ¬
		my enumConstant("pEeF00F60F4E"), ¬
		my enumConstant("pEeF00F60F50"), ¬
		my enumConstant("pEeF00F60F4F"), ¬
		my enumConstant("pEeF00F60F48"), ¬
		my enumConstant("pEeF00F60F49"), ¬
		my enumConstant("pEeF00F60F46"), ¬
		my enumConstant("pEeF00F60F47"), ¬
		my enumConstant("pEeF00F60F0A"), ¬
		my enumConstant("pEeF00F60D1D"), ¬
		my enumConstant("pEeF00F60E02"), ¬
		my enumConstant("pEeF00F60E01"), ¬
		my enumConstant("pEeF00F60E04"), ¬
		my enumConstant("pEeF00F60E03"), ¬
		my enumConstant("pEeF00F60D17"), ¬
		my enumConstant("pEeF00F60D1B"), ¬
		my enumConstant("pEeF00F60D18"), ¬
		my enumConstant("pEeF00F60D1A"), ¬
		my enumConstant("pEeF00F60D19"), ¬
		my enumConstant("pEeF00F60A03"), ¬
		my enumConstant("pEeF00F60A04"), ¬
		my enumConstant("pEeF00F60A07"), ¬
		my enumConstant("pEeF00F60A05"), ¬
		my enumConstant("pEeF00F60A08"), ¬
		my enumConstant("pEeF00F60A06"), ¬
		my enumConstant("pEeF00F60A01"), ¬
		my enumConstant("pEeF00F60A02"), ¬
		my enumConstant("pEeF00F60F40"), ¬
		my enumConstant("pEeF00F60F3D"), ¬
		my enumConstant("pEeF00F60F3F"), ¬
		my enumConstant("pEeF00F60F3E"), ¬
		my enumConstant("pEeF00F60D1C"), ¬
		my enumConstant("pEeF00F60804"), ¬
		my enumConstant("pEeF00F60807"), ¬
		my enumConstant("pEeF00F60805"), ¬
		my enumConstant("pEeF00F60801"), ¬
		my enumConstant("pEeF00F60808"), ¬
		my enumConstant("pEeF00F60806"), ¬
		my enumConstant("pEeF00F60803"), ¬
		my enumConstant("pEeF00F60802"), ¬
		my enumConstant("pEeF00F5FFFE"), ¬
		my enumConstant("pEeF00F60F1A"), ¬
		my enumConstant("pEeF00F60F17"), ¬
		my enumConstant("pEeF00F60F19"), ¬
		my enumConstant("pEeF00F60F18"), ¬
		my enumConstant("pEeF00F60F30"), ¬
		my enumConstant("pEeF00F60F31"), ¬
		my enumConstant("pEeF00F60F10"), ¬
		my enumConstant("pEeF00F60F11"), ¬
		my enumConstant("pEeF00F60F12"), ¬
		my enumConstant("pEeF00F60F13"), ¬
		my enumConstant("pEeF00F60F14"), ¬
		my enumConstant("pEeF00F60F15"), ¬
		my enumConstant("pEeF00F60F16"), ¬
		my enumConstant("pEeF00F60F63"), ¬
		my enumConstant("pEeF00F60F64"), ¬
		my enumConstant("pEeF00F60F2F"), ¬
		my enumConstant("pEeF00F60F2E"), ¬
		my enumConstant("pEeF00F60B04"), ¬
		my enumConstant("pEeF00F60B01"), ¬
		my enumConstant("pEeF00F60B03"), ¬
		my enumConstant("pEeF00F60B02"), ¬
		my enumConstant("pEeF00F60D16"), ¬
		my enumConstant("pEeF00F60D15"), ¬
		my enumConstant("pEeF00F60D12"), ¬
		my enumConstant("pEeF00F60D11"), ¬
		my enumConstant("pEeF00F60D14"), ¬
		my enumConstant("pEeF00F60D13")}
end eppEntryEffectConstants

on eppEntryEffectNames()
	return {"entry effect airplane left", ¬
		"entry effect airplane right", ¬
		"entry effect appear", ¬
		"entry effect blinds horizontal", ¬
		"entry effect blinds vertical", ¬
		"entry effect box down", ¬
		"entry effect box in", ¬
		"entry effect box left", ¬
		"entry effect box out", ¬
		"entry effect box right", ¬
		"entry effect box up", ¬
		"entry effect checkerboard across", ¬
		"entry effect checkerboard down", ¬
		"entry effect circle", ¬
		"entry effect collapse across", ¬
		"entry effect collapse bottom", ¬
		"entry effect collapse left", ¬
		"entry effect collapse right", ¬
		"entry effect collapse up", ¬
		"entry effect crush", ¬
		"entry effect comb horizontal", ¬
		"entry effect comb vertical", ¬
		"entry effect conveyor left", ¬
		"entry effect conveyor right", ¬
		"entry effect cover down", ¬
		"entry effect cover left down", ¬
		"entry effect cover left up", ¬
		"entry effect cover left", ¬
		"entry effect cover right down", ¬
		"entry effect cover right up", ¬
		"entry effect cover right", ¬
		"entry effect cover up", ¬
		"entry effect crawl from down", ¬
		"entry effect crawl from left", ¬
		"entry effect crawl from right", ¬
		"entry effect crawl from up", ¬
		"entry effect cube down", ¬
		"entry effect cube left", ¬
		"entry effect cube right", ¬
		"entry effect cube up", ¬
		"entry effect curtains", ¬
		"entry effect cut black", ¬
		"entry effect cut", ¬
		"entry effect diamond", ¬
		"entry effect dissolve", ¬
		"entry effect doors horizontal", ¬
		"entry effect doors vertical", ¬
		"entry effect drape left", ¬
		"entry effect drape right", ¬
		"entry effect fade black", ¬
		"entry effect fade fly from bottom left", ¬
		"entry effect fade fly from bottom right", ¬
		"entry effect fade fly from bottom", ¬
		"entry effect fade fly from left", ¬
		"entry effect fade fly from right", ¬
		"entry effect fade fly from top left", ¬
		"entry effect fade fly from top right", ¬
		"entry effect fade fly from top", ¬
		"entry effect fade smoothly", ¬
		"entry effect fade", ¬
		"entry effect fall over left", ¬
		"entry effect fall over right", ¬
		"entry effect ferris wheel left", ¬
		"entry effect ferris wheel right", ¬
		"entry effect flash once fast", ¬
		"entry effect flash once medium", ¬
		"entry effect flash once slow", ¬
		"entry effect flashbulb", ¬
		"entry effect flip down", ¬
		"entry effect flip left", ¬
		"entry effect flip right", ¬
		"entry effect flip up", ¬
		"entry effect fly from bottom left", ¬
		"entry effect fly from bottom right", ¬
		"entry effect fly from bottom", ¬
		"entry effect fly from left", ¬
		"entry effect fly from right", ¬
		"entry effect fly from top left", ¬
		"entry effect fly from top right", ¬
		"entry effect fly from top", ¬
		"entry effect fly through in bounce", ¬
		"entry effect fly through in", ¬
		"entry effect fly through out bounce", ¬
		"entry effect fly through out", ¬
		"entry effect fracture", ¬
		"entry effect gallery left", ¬
		"entry effect gallery right", ¬
		"entry effect glitter diamond down", ¬
		"entry effect glitter diamond left", ¬
		"entry effect glitter diamond right", ¬
		"entry effect glitter diamond up", ¬
		"entry effect glitter hexagon down", ¬
		"entry effect glitter hexagon left", ¬
		"entry effect glitter hexagon right", ¬
		"entry effect glitter hexagon up", ¬
		"entry effect honeycomb", ¬
		"entry effect morph by object", ¬
		"entry effect morph by word", ¬
		"entry effect morph by char", ¬
		"entry effect news flash", ¬
		"entry effect none", ¬
		"entry effect orbit down", ¬
		"entry effect orbit left", ¬
		"entry effect orbit right", ¬
		"entry effect orbit up", ¬
		"entry effect origami left", ¬
		"entry effect origami right", ¬
		"entry effect page curl double left", ¬
		"entry effect page curl double right", ¬
		"entry effect page curl single left", ¬
		"entry effect page curl single right", ¬
		"entry effect pan down", ¬
		"entry effect pan left", ¬
		"entry effect pan right", ¬
		"entry effect pan up", ¬
		"entry effect peek from down", ¬
		"entry effect peek from left", ¬
		"entry effect peek from right", ¬
		"entry effect peek from up", ¬
		"entry effect peel off left", ¬
		"entry effect peel off right", ¬
		"entry effect plus", ¬
		"entry effect prestige", ¬
		"entry effect push down", ¬
		"entry effect push left", ¬
		"entry effect push right", ¬
		"entry effect push up", ¬
		"entry effect random bars horizontal", ¬
		"entry effect random bars vertical", ¬
		"entry effect random", ¬
		"entry effect reveal black left", ¬
		"entry effect reveal black right", ¬
		"entry effect reveal smooth left", ¬
		"entry effect reveal smooth right", ¬
		"entry effect ripple center", ¬
		"entry effect ripple left down", ¬
		"entry effect ripple left up", ¬
		"entry effect ripple right down", ¬
		"entry effect ripple right up", ¬
		"entry effect rotate down", ¬
		"entry effect rotate left", ¬
		"entry effect rotate right", ¬
		"entry effect rotate up", ¬
		"entry effect shred rectangle in", ¬
		"entry effect shred rectangle out", ¬
		"entry effect shred strips in", ¬
		"entry effect shred strips out", ¬
		"entry effect spinner", ¬
		"entry effect spiral", ¬
		"entry effect split horizontal in", ¬
		"entry effect split horizontal out", ¬
		"entry effect split vertical in", ¬
		"entry effect split vertical out", ¬
		"entry effect stretch across", ¬
		"entry effect stretch down", ¬
		"entry effect stretch left", ¬
		"entry effect stretch right", ¬
		"entry effect stretch up", ¬
		"entry effect strips down left", ¬
		"entry effect strips down right", ¬
		"entry effect strips left down", ¬
		"entry effect strips left up", ¬
		"entry effect strips right down", ¬
		"entry effect strips right up", ¬
		"entry effect strips up left", ¬
		"entry effect strips up right", ¬
		"entry effect switch down", ¬
		"entry effect switch left", ¬
		"entry effect switch right", ¬
		"entry effect switch up", ¬
		"entry effect swivel", ¬
		"entry effect uncover down", ¬
		"entry effect uncover left down", ¬
		"entry effect uncover left up", ¬
		"entry effect uncover left", ¬
		"entry effect uncover right down", ¬
		"entry effect uncover right up", ¬
		"entry effect uncover right", ¬
		"entry effect uncover up", ¬
		"entry effect unset", ¬
		"entry effect vortex down", ¬
		"entry effect vortex left", ¬
		"entry effect vortex right", ¬
		"entry effect vortex up", ¬
		"entry effect warp in", ¬
		"entry effect warp out", ¬
		"entry effect wedge", ¬
		"entry effect wheel 1 spoke", ¬
		"entry effect wheel 2 spokes", ¬
		"entry effect wheel 3 spokes", ¬
		"entry effect wheel 4 spokes", ¬
		"entry effect wheel 8 spokes", ¬
		"entry effect wheel reverse 1 spoke", ¬
		"entry effect wind left", ¬
		"entry effect wind right", ¬
		"entry effect window horizontal", ¬
		"entry effect window vertical", ¬
		"entry effect wipe down", ¬
		"entry effect wipe left", ¬
		"entry effect wipe right", ¬
		"entry effect wipe up", ¬
		"entry effect zoom bottom", ¬
		"entry effect zoom center", ¬
		"entry effect zoom in slightly", ¬
		"entry effect zoom in", ¬
		"entry effect zoom out slightly", ¬
		"entry effect zoom out"}
end eppEntryEffectNames

on eppEntryEffectCodes()
	return {"0x00f60f6e", ¬
		"0x00f60f6f", ¬
		"0x00f60f04", ¬
		"0x00f60301", ¬
		"0x00f60302", ¬
		"0x00f60f55", ¬
		"0x00f60c02", ¬
		"0x00f60f52", ¬
		"0x00f60c01", ¬
		"0x00f60f54", ¬
		"0x00f60f53", ¬
		"0x00f60401", ¬
		"0x00f60402", ¬
		"0x00f60f05", ¬
		"0x00f60d17", ¬
		"0x00f60d1b", ¬
		"0x00f60d18", ¬
		"0x00f60d1a", ¬
		"0x00f60d19", ¬
		"0x00f60f67", ¬
		"0x00f60f07", ¬
		"0x00f60f08", ¬
		"0x00f60f2a", ¬
		"0x00f60f2b", ¬
		"0x00f60504", ¬
		"0x00f60507", ¬
		"0x00f60505", ¬
		"0x00f60501", ¬
		"0x00f60508", ¬
		"0x00f60506", ¬
		"0x00f60503", ¬
		"0x00f60502", ¬
		"0x00f60d10", ¬
		"0x00f60d0d", ¬
		"0x00f60d0f", ¬
		"0x00f60d0e", ¬
		"0x00f60f4d", ¬
		"0x00f60f4a", ¬
		"0x00f60f4b", ¬
		"0x00f60f4c", ¬
		"0x00f60f62", ¬
		"0x00f60102", ¬
		"0x00f60101", ¬
		"0x00f60f06", ¬
		"0x00f60601", ¬
		"0x00f60f2d", ¬
		"0x00f60f2c", ¬
		"0x00f60f60", ¬
		"0x00f60f61", ¬
		"0x00f60701", ¬
		"0x00f60d24", ¬
		"0x00f60d25", ¬
		"0x00f60d21", ¬
		"0x00f60d1e", ¬
		"0x00f60d20", ¬
		"0x00f60d22", ¬
		"0x00f60d23", ¬
		"0x00f60d1f", ¬
		"0x00f60f09", ¬
		"0x00f60f09", ¬
		"0x00f60f5e", ¬
		"0x00f60f5f", ¬
		"0x00f60f3b", ¬
		"0x00f60f3c", ¬
		"0x00f60f01", ¬
		"0x00f60f02", ¬
		"0x00f60f03", ¬
		"0x00f60f45", ¬
		"0x00f60f44", ¬
		"0x00f60f41", ¬
		"0x00f60f42", ¬
		"0x00f60f43", ¬
		"0x00f60d07", ¬
		"0x00f60d08", ¬
		"0x00f60d04", ¬
		"0x00f60d01", ¬
		"0x00f60d03", ¬
		"0x00f60d05", ¬
		"0x00f60d06", ¬
		"0x00f60d02", ¬
		"0x00f60f34", ¬
		"0x00f60f32", ¬
		"0x00f60f35", ¬
		"0x00f60f33", ¬
		"0x00f60f66", ¬
		"0x00f60f28", ¬
		"0x00f60f29", ¬
		"0x00f60f23", ¬
		"0x00f60f20", ¬
		"0x00f60f22", ¬
		"0x00f60f21", ¬
		"0x00f60f27", ¬
		"0x00f60f24", ¬
		"0x00f60f26", ¬
		"0x00f60f25", ¬
		"0x00f60f3a", ¬
		"0x00f60f72", ¬
		"0x00f60f73", ¬
		"0x00f60f74", ¬
		"0x00f60f0a", ¬
		"0x00f60000", ¬
		"0x00f60f59", ¬
		"0x00f60f56", ¬
		"0x00f60f58", ¬
		"0x00f60f57", ¬
		"0x00f60f70", ¬
		"0x00f60f71", ¬
		"0x00f60f6c", ¬
		"0x00f60f6d", ¬
		"0x00f60f6a", ¬
		"0x00f60f6b", ¬
		"0x00f60f5d", ¬
		"0x00f60f5a", ¬
		"0x00f60f5c", ¬
		"0x00f60f5b", ¬
		"0x00f60d0a", ¬
		"0x00f60d09", ¬
		"0x00f60d0b", ¬
		"0x00f60d0c", ¬
		"0x00f60f68", ¬
		"0x00f60f69", ¬
		"0x00f60f0b", ¬
		"0x00f60f65", ¬
		"0x00f60f0c", ¬
		"0x00f60f0d", ¬
		"0x00f60f0e", ¬
		"0x00f60f0f", ¬
		"0x00f60901", ¬
		"0x00f60902", ¬
		"0x00f60201", ¬
		"0x00f60f38", ¬
		"0x00f60f39", ¬
		"0x00f60f36", ¬
		"0x00f60f37", ¬
		"0x00f60f1b", ¬
		"0x00f60f1e", ¬
		"0x00f60f1d", ¬
		"0x00f60f1f", ¬
		"0x00f60f1c", ¬
		"0x00f60f51", ¬
		"0x00f60f4e", ¬
		"0x00f60f50", ¬
		"0x00f60f4f", ¬
		"0x00f60f48", ¬
		"0x00f60f49", ¬
		"0x00f60f46", ¬
		"0x00f60f47", ¬
		"0x00f60f0a", ¬
		"0x00f60d1d", ¬
		"0x00f60e02", ¬
		"0x00f60e01", ¬
		"0x00f60e04", ¬
		"0x00f60e03", ¬
		"0x00f60d17", ¬
		"0x00f60d1b", ¬
		"0x00f60d18", ¬
		"0x00f60d1a", ¬
		"0x00f60d19", ¬
		"0x00f60a03", ¬
		"0x00f60a04", ¬
		"0x00f60a07", ¬
		"0x00f60a05", ¬
		"0x00f60a08", ¬
		"0x00f60a06", ¬
		"0x00f60a01", ¬
		"0x00f60a02", ¬
		"0x00f60f40", ¬
		"0x00f60f3d", ¬
		"0x00f60f3f", ¬
		"0x00f60f3e", ¬
		"0x00f60d1c", ¬
		"0x00f60804", ¬
		"0x00f60807", ¬
		"0x00f60805", ¬
		"0x00f60801", ¬
		"0x00f60808", ¬
		"0x00f60806", ¬
		"0x00f60803", ¬
		"0x00f60802", ¬
		"0x00f5fffe", ¬
		"0x00f60f1a", ¬
		"0x00f60f17", ¬
		"0x00f60f19", ¬
		"0x00f60f18", ¬
		"0x00f60f30", ¬
		"0x00f60f31", ¬
		"0x00f60f10", ¬
		"0x00f60f11", ¬
		"0x00f60f12", ¬
		"0x00f60f13", ¬
		"0x00f60f14", ¬
		"0x00f60f15", ¬
		"0x00f60f16", ¬
		"0x00f60f63", ¬
		"0x00f60f64", ¬
		"0x00f60f2f", ¬
		"0x00f60f2e", ¬
		"0x00f60b04", ¬
		"0x00f60b01", ¬
		"0x00f60b03", ¬
		"0x00f60b02", ¬
		"0x00f60d16", ¬
		"0x00f60d15", ¬
		"0x00f60d12", ¬
		"0x00f60d11", ¬
		"0x00f60d14", ¬
		"0x00f60d13"}
end eppEntryEffectCodes
-- <<< END GENERATED sdef CANDIDATE ARRAYS <<<
