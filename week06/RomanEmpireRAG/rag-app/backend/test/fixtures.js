/**
 * A tiny stand-in corpus. Every unit test uses these chunks so it exercises
 * the answer and HTTP paths without reading the 9 MB of Gibbon, and so the
 * expected passage text is obvious to a human reading the test.
 */
export const chunks = [
  {
    id: 'v1-00001',
    volume: 1,
    chapter: 'Chapter VI: Death Of Severus, Tyranny Of Caracalla.',
    text:
      'Caracalla granted the Roman citizenship to every free inhabitant of the ' +
      'empire by the Antonine Constitution. The edict extended the law of Rome ' +
      'to the provinces, and it was received with little gratitude.',
    chars: 220,
    words: 38,
    tokens: 55,
  },
  {
    id: 'v2-00002',
    volume: 2,
    chapter: 'Chapter XXVI: Progress Of The Huns.',
    text:
      'The Goths destroyed the Roman army in the battle of Adrianople, and the ' +
      'emperor Valens perished in the rout. The defeat exposed the weakness of ' +
      'the frontier and opened Italy to the barbarians.',
    chars: 215,
    words: 37,
    tokens: 54,
  },
  {
    id: 'v4-00003',
    volume: 4,
    chapter: 'Chapter XLIII: Last Victory And Death Of Belisarius.',
    text:
      'Belisarius defended Rome against the Goths with a small band of veterans. ' +
      'The plague of Justinian depopulated the empire while the war continued, ' +
      'and the cities of the East never recovered their former greatness.',
    chars: 220,
    words: 38,
    tokens: 55,
  },
  {
    id: 'v1-00004',
    volume: 1,
    chapter: 'Chapter I: The Extent Of The Empire In The Age Of The Antonines.',
    text:
      'The Roman empire in the age of the Antonines stretched from the Atlantic ' +
      'to the Euphrates, and its provinces were governed by magistrates sent ' +
      'from Rome.',
    chars: 175,
    words: 30,
    tokens: 44,
  },
  {
    id: 'v1-00005',
    volume: 1,
    chapter: 'Chapter X: Emperors Decius, Gallus, Aemilianus, Valerian.',
    text:
      'The emperor Decius fell in battle against the Goths in the marshes of ' +
      'the Danube. His successor Gallus purchased a shameful peace, and the ' +
      'barbarians returned to the attack.',
    chars: 190,
    words: 32,
    tokens: 47,
  },
  {
    id: 'v3-00006',
    volume: 3,
    chapter: 'Chapter XXXVI: Total Extinction Of The Western Empire.',
    text:
      'The Western empire expired in the person of Augustulus, and the name of ' +
      'Rome was preserved only in the Eastern capital. The barbarian kings ' +
      'ruled Italy in the name of the emperor at Constantinople.',
    chars: 215,
    words: 37,
    tokens: 54,
  },
];
