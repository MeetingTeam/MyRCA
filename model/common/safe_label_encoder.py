from sklearn.preprocessing import LabelEncoder
import numpy as np

class SafeLabelEncoder:
    def __init__(self, unknown_token="__UNK__"):
        self.unknown_token = unknown_token
        self.fitted = False

    def fit(self, values):
        unique_vals = list(set(values))

        # Fit without unknown token first
        self.le = LabelEncoder()
        self.le.fit(unique_vals)

        # Append unknown token as LAST class
        classes = list(self.le.classes_) + [self.unknown_token]
        self.classes = np.array(classes)

        # Rebuild a new encoder with updated class list
        self.le.classes_ = self.classes

        # Unknown index is LAST
        self.unknown_index = len(self.classes) - 1

        self.fitted = True
        return self

    def transform(self, values):
        if not self.fitted:
            raise RuntimeError("SafeLabelEncoder must be fitted first")

        known_classes = set(self.classes)
        result = []
        for v in values:
            if v in known_classes:
                result.append(int(self.le.transform([v])[0]))
            else:
                result.append(self.unknown_index)
        return np.array(result, dtype=np.int64)

    def fit_transform(self, values):
        self.fit(values)
        return self.transform(values)

    def inverse_transform(self, indices):
        result = []
        for idx in indices:
            if idx == self.unknown_index:
                result.append(self.unknown_token)
            else:
                result.append(self.le.inverse_transform([idx])[0])
        return np.array(result)

    def classes_(self):
        return self.classes

    def get_unknown_index(self):
        return self.unknown_index