export type Bot = {
	id: string
	version: string
}

type DriveMotor = {
	type: "drive"
	botId: string
	motorId: number
	speed: number
}

type Stop = {
	type: "stop"
	botId: string
}

type StopAllMotors = {
        type: "stopAllMotors"
        botId: string
}

type TurnServo = {
        type: "turnServo"
        botId: string
        angle: number
}

export type MsgToServer = DriveMotor | Stop | StopAllMotors | TurnServo

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
export type MsgToBot =
    | Omit<DriveMotor, "botId">
    | Omit<Stop, "botId">
    | Ping
    | StopAllMotors
    | Omit<TurnServo, "botId">

// export type MyInfo = {
// 	type: "myInfo"
// 	version: string
// }

// export type Pong = {
// 	type: "pong"
// }

// export type MsgFromBot = MyInfo | Pong
