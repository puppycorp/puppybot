
export type Bot = {
	id: string
	version: string
}

type Drive = {
	type: "drive"
	botId: string
	motorId: number
	// speed: number // -100% to 100%
	// angle: number // Turning angle -100% to 100%
}

type Stop = {
	type: "stop"
	botId: string
}

type StopAllMotors = {
	type: "stopAllMotors"
	botId: string
}

export type MsgToServer = Drive | Stop | StopAllMotors

export type BotConnected = {
	type: "botConnected"
	botId: string
}

export type BotDisconnected = {
	type: "botDisconnected"
	botId: string
}

export type BotInfo = {
	type: "botInfo"
	botId: string
	version: string
}

export type Ping = {
	type: "ping"
}

export type MsgToUi = BotConnected | BotDisconnected | BotInfo
export type MsgToBot = Omit<Drive, "botId"> | Omit<Stop, "botId"> | Ping | StopAllMotors

// export type MyInfo = {
// 	type: "myInfo"
// 	version: string
// }

// export type Pong = {
// 	type: "pong"
// }

// export type MsgFromBot = MyInfo | Pong