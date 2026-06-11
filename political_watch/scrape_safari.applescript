-- 用既有 Safari 登入 session,在背景分頁依序抓追蹤名單貼文,輸出 JSON 行。
-- 不 activate Safari、不設 current tab → 不搶使用者焦點(已驗證前景保持原 app)。
-- 由 watch_safari.py 呼叫;handles 以逗號分隔當參數傳入。
on run argv
	set handleStr to item 1 of argv
	set AppleScript's text item delimiters to ","
	set handles to text items of handleStr
	set AppleScript's text item delimiters to ""
	set jsExtract to "(() => { const out=[]; for (const a of document.querySelectorAll('article')) { const t=a.querySelector('time'); const link=t?t.closest('a'):null; const tx=a.querySelector('[data-testid=\"tweetText\"]'); if(!t||!link||!tx) continue; if(a.querySelector('[data-testid=\"socialContext\"]')) continue; out.push({time:t.getAttribute('datetime'), url:'https://x.com'+link.getAttribute('href'), text:tx.innerText}); if(out.length>=6) break; } return JSON.stringify(out); })()"
	set outLines to ""
	tell application "Safari"
		if (count of windows) is 0 then return "ERR:NO_WINDOW"
		set w to front window
		repeat with h in handles
			try
				set scrapeTab to make new tab at end of tabs of w with properties {URL:"https://x.com/" & h}
				delay 7
				set res to do JavaScript jsExtract in scrapeTab
				close scrapeTab
				set outLines to outLines & h & "\t" & res & linefeed
			on error errMsg
				try
					close scrapeTab
				end try
				set outLines to outLines & h & "\tERR:" & errMsg & linefeed
			end try
		end repeat
	end tell
	return outLines
end run
