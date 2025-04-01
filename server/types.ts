
type Drive = {
	type: "drive"
	botId: string
	speed: number // -100% to 100%
	angle: number // Turning angle -100% to 100%
}

type Stop = {
	type: "stop"
	botId: string
}

export type MsgToServer = Drive | Stop
