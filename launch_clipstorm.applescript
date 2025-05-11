tell application "Terminal"
    do script "cd " & quoted form of POSIX path of "/Users/tylerscheviak/clipstorm" & " && streamlit run clipstorm_streamlit.py"
end tell 