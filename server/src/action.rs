struct Roll {
    value: u8,
}

enum Stage1Action {
    Roll,
    Challenge,
}

enum Stage2Action {
    Claim(Roll),
    Reroll,
}
