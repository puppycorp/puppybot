
type DriveMotor = {
	type: "drive"
	speed: number,
	direction: "forward" | "backward"
}

type StopMotor = {
	type: "stop"
}

export type MsgToServer = DriveMotor | StopMotor



// export type MsgFromClient