use rand::Rng;

/// Meyer (2,1) is the highest-ranked roll.
pub const MEYER: u8 = 21;

/// Rolls two dice and returns the rank of the outcome.
pub fn roll(rng: &mut impl Rng) -> u8 {
    rank((rng.random_range(1..=6), rng.random_range(1..=6)))
}

/// Rank of a roll, from 1 (3-2, lowest) to 21 (Meyer).
///
/// Ordering: Meyer (2,1) > Lille Meyer (3,1) > pairs 6-6..1-1 > 6-5 down to 3-2.
fn rank(dice: (u8, u8)) -> u8 {
    const PLAIN: [(u8, u8); 13] = [
        (3, 2),
        (4, 1),
        (4, 2),
        (4, 3),
        (5, 1),
        (5, 2),
        (5, 3),
        (5, 4),
        (6, 1),
        (6, 2),
        (6, 3),
        (6, 4),
        (6, 5),
    ];
    let (a, b) = (dice.0.max(dice.1), dice.0.min(dice.1));
    match (a, b) {
        (2, 1) => MEYER,
        (3, 1) => 20,
        _ if a == b => 13 + a,
        _ => PLAIN.iter().position(|&p| p == (a, b)).unwrap() as u8 + 1,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn ranks_are_ordered() {
        assert_eq!(rank((1, 2)), MEYER);
        assert_eq!(rank((1, 3)), 20);
        assert_eq!(rank((6, 6)), 19);
        assert_eq!(rank((1, 1)), 14);
        assert_eq!(rank((6, 5)), 13);
        assert_eq!(rank((2, 3)), 1);
    }

    #[test]
    fn all_rolls_cover_all_ranks() {
        let mut ranks: Vec<u8> = (1..=6)
            .flat_map(|a| (1..=a).map(move |b| rank((a, b))))
            .collect();
        ranks.sort_unstable();
        assert_eq!(ranks, (1..=21).collect::<Vec<u8>>());
    }
}
