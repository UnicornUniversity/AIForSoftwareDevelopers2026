/**
 * A tiny stand-in corpus. Every unit test uses these sections so it exercises
 * the answer and HTTP paths without reading the twelve Markdown documents or
 * opening ChromaDB, and so the expected passage text is obvious to a human
 * reading the test.
 */
export const chunks = [
  {
    id: 'd01-key-information',
    docId: '01_diabetes_diagnosis',
    docNumber: 1,
    title: 'Diabetes Diagnosis',
    section: 'Key information',
    topic: 'Diagnostic criteria for diabetes mellitus',
    source: 'WHO Classification of Diabetes Mellitus (2019); ADA Standards of Care (2024)',
    text:
      'Fasting plasma glucose at or above 7.0 mmol/L, a two-hour plasma ' +
      'glucose at or above 11.1 mmol/L during an oral glucose tolerance test, ' +
      'or an HbA1c at or above 6.5% all establish diabetes. An asymptomatic ' +
      'person needs a second confirmatory test.',
  },
  {
    id: 'd02-overview',
    docId: '02_hba1c',
    docNumber: 2,
    title: 'HbA1c (Glycated Haemoglobin)',
    section: 'Overview',
    topic: 'Glycated haemoglobin and its use in diagnosis and monitoring',
    source: 'ADA Standards of Care (2024); WHO (2011)',
    text:
      'HbA1c reflects average plasma glucose over the preceding two to three ' +
      'months. It is used both to diagnose diabetes and to monitor glycaemic ' +
      'control, but it is not reliable in pregnancy or in some haemoglobinopathies.',
  },
  {
    id: 'd09-key-information',
    docId: '09_diabetic_ketoacidosis',
    docNumber: 9,
    title: 'Diabetic Ketoacidosis (DKA)',
    section: 'Key information',
    topic: 'Diabetic ketoacidosis — recognition, diagnosis, and management outline',
    source: 'ADA/EASD Hyperglycemic Crises in Adults with Diabetes (2024)',
    text:
      'Diabetic ketoacidosis requires hyperglycaemia, ketonaemia and metabolic ' +
      'acidosis. Immediate management is fluid resuscitation, intravenous ' +
      'insulin, potassium replacement and treatment of the precipitating cause.',
  },
  {
    id: 'd12-key-information',
    docId: '12_medications',
    docNumber: 12,
    title: 'Medications for Diabetes',
    section: 'Key information',
    topic: 'Overview of glucose-lowering medication classes used in diabetes',
    source: 'ADA Standards of Care (2024); NICE guideline NG28',
    text:
      'Metformin is the traditional first-line agent for type 2 diabetes. ' +
      'SGLT2 inhibitors lower HbA1c modestly and protect the heart and kidneys ' +
      'in people with established cardiovascular or renal disease.',
  },
  {
    id: 'd08-key-information',
    docId: '08_prediabetes',
    docNumber: 8,
    title: 'Prediabetes',
    section: 'Key information',
    topic: 'Definition and management of prediabetes',
    source: 'ADA Standards of Care (2024)',
    text:
      'Prediabetes is defined by glucose values above the normal range but ' +
      'below the diagnostic thresholds for diabetes. Lifestyle change reduces ' +
      'the risk of progression to type 2 diabetes.',
  },
  {
    id: 'd10-examples',
    docId: '10_hypoglycemia',
    docNumber: 10,
    title: 'Hypoglycaemia',
    section: 'Examples',
    topic: 'Recognition and management of hypoglycaemia',
    source: 'ADA Standards of Care (2024); NICE guideline NG17',
    text:
      'A patient taking a sulfonylurea develops sweating, tremor and confusion ' +
      'with a capillary glucose of 3.1 mmol/L. This is hypoglycaemia and is ' +
      'treated with fast-acting oral carbohydrate.',
  },
];
