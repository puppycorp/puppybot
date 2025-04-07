import type { MsgFromBot, MsgToBot } from "./types"

enum CommandType {
	SendInstructions = 1,
	StopAll = 2,
	ReplaceBlock = 3,
	PauseAll = 4,
	ResumeAll = 5,
}

enum InstructionType {
	Sleep = 1,
	Stop = 2,
	DoUntil = 3,
	Drive = 4,
}

enum Operator {
	Equal = 1,
	NotEqual = 2,
	GreaterThan = 3,
	LessThan = 4,
	GreaterThanOrEqual = 5,
	LessThanOrEqual = 6,
	And = 7,
	Or = 8,
	Forever = 9
}

type ConditionFrame = {
	targetId: number
	fieldId: number
	operator: Operator
	value: number
}

type DoUntilCondition = {
	type: InstructionType.DoUntil
	targetId: number
	instruction: InstructionType.Drive,
}

type StopAll = {
	type: CommandType.StopAll
}

type Command = StopAll

const header = (cmd: Command) => {

}

type Instruction = {
	type: InstructionType
	args: any[]
}

const block = (instructions: Instruction[]) => {
	
}

export const encodeBotMsg = (msg: MsgToBot): Buffer => {
	const buffer = Buffer.alloc(4 + msg.length)
	buffer.writeUInt32BE(msg.length, 0)
	buffer.write(msg, 4)
	return buffer
}

export const decodeBotMsg = (buffer: Buffer): MsgFromBot => {
	
}