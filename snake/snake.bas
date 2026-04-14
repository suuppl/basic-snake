10 ' SNAKE.BAS
20 PRINT "enter snake.bas"
30 GOTO 200 ' >> [ INIT ]

100 '[ MAIN ]
110 PRINT "enter main"
120 ' PRINT "Snake3 initialized successfully"
130 PRINT "W ="; W; " H ="; H
140 GOSUB 400 ' >> [ TEST ]
150 END

200 '[ INIT ]
210 PRINT "enter init"
220 W = 20: H = 20: TOPB = 2: LEFTB = 10
230 DIM HS(10)
240 DIM HN$(10)
250 DIM X(200), Y(200)
260 DIM GRID(W,H)
270 DEF FNX(I) = Y(I) + TOPB
280 DEF FNY(I) = X(I) + LEFTB
290 DEF FNGRID(I) = GRID(X(I),Y(I))
300 GOTO 100 ' >> [ MAIN ]

400 '[ TEST ]
410 PRINT "Test!"
420 RETURN
