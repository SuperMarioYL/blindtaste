Output docs/demo/battery-run.gif
Set FontSize 14
Set Width 1040
Set Height 640
Set Padding 12
Set TypingSpeed 22ms
Set Framerate 12

# 演示环境清理（保证每次渲染都从头开始）
Type "rm -rf /tmp/blindtaste-demo-gif"
Enter
Sleep 300ms

# 1) init：8 道选择题 -> 6-10 条任务电池
Type "BLINDTASTE_HOME=/tmp/blindtaste-demo-gif blindtaste init"
Enter
Sleep 500ms
Type "1,2,3,4"
Enter
Sleep 300ms
Type "1"
Enter
Sleep 300ms
Type "1"
Enter
Sleep 300ms
Type "1"
Enter
Sleep 300ms
Type "1"
Enter
Sleep 300ms
Type "2"
Enter
Sleep 300ms
Enter
Sleep 300ms
Type "1,2,4"
Enter
Sleep 1s

# 2) run --demo：匿名 A/B 盲选（不配 key、不调用 API）
Type "BLINDTASTE_HOME=/tmp/blindtaste-demo-gif blindtaste run --demo --limit 2"
Enter
Sleep 1s
Type "a"
Enter
Sleep 800ms
Type "b"
Enter
Sleep 800ms

# 3) report：当前进度与票面统计
Type "BLINDTASTE_HOME=/tmp/blindtaste-demo-gif blindtaste report"
Enter
Sleep 2s
