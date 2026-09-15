"""Load only versioned local trusted artifacts with verified content/dependencies."""
import hashlib
import json
import re
from functools import lru_cache
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import sklearn

from app.predictive.features import FEATURES, FEATURE_VERSION, UNITS

LEGACY_FEATURE_VERSIONS = frozenset({'asof_operational_v1'})


class ModelArtifactError(ValueError):
    pass


@lru_cache(maxsize=4)
def _load(path, metadata_hash, artifact_signature=None):
    path = Path(path)
    metadata = json.loads((path/'metadata.json').read_text(encoding='utf-8'))
    if not isinstance(metadata, dict) or not isinstance(metadata.get('files'),dict) or 'models.joblib' not in metadata['files']:
        raise ModelArtifactError('Model metadata requires a verified models.joblib artifact')
    if hashlib.sha256((path/'metadata.json').read_bytes()).hexdigest() != metadata_hash:
        raise ModelArtifactError('Model metadata checksum mismatch')
    feature_version = metadata.get('feature_version')
    feature_names = metadata.get('features')
    if feature_version == FEATURE_VERSION:
        if feature_names != FEATURES:
            raise ModelArtifactError('Model feature schema is incompatible')
        if metadata.get('units') != UNITS:
            raise ModelArtifactError('Model feature units are incompatible')
    elif feature_version in LEGACY_FEATURE_VERSIONS:
        # The portable demo ships a signed v1 model. v2 adds derived capacity
        # features but retains every v1 field with the same meaning and unit.
        # Keep the model's recorded order at inference rather than silently
        # substituting or reordering inputs.
        if (not isinstance(feature_names, list) or len(feature_names) != len(set(feature_names))
                or not set(feature_names) <= set(FEATURES)):
            raise ModelArtifactError('Model feature schema is incompatible')
        if metadata.get('units') != {name: UNITS[name] for name in feature_names}:
            raise ModelArtifactError('Model feature units are incompatible')
    else:
        raise ModelArtifactError('Model feature schema is incompatible')
    if not {'model_version','trained_at','observation_cutoff','quality','selected_models','dataset_rows','evaluation','labels','assumptions'} <= metadata.keys():
        raise ModelArtifactError('Model operational metadata schema is incomplete')
    installed = dict(sklearn=sklearn.__version__, numpy=np.__version__, pandas=pd.__version__, joblib=joblib.__version__)
    if any(metadata['dependencies'][key] != value for key, value in installed.items()):
        raise ModelArtifactError('Model dependencies differ; retrain with the installed environment')
    for filename, checksum in metadata['files'].items():
        file_path = (path/filename).resolve()
        if not file_path.is_relative_to(path.resolve()) or hashlib.sha256(file_path.read_bytes()).hexdigest() != checksum:
            raise ModelArtifactError('Model artifact checksum mismatch')
    # Pickle/joblib can execute code: artifacts must come from this trusted local training CLI.
    try:
        bundle = joblib.load(path/'models.joblib')
    except Exception as error:
        raise ModelArtifactError('Model bundle could not be loaded') from error
    if not isinstance(bundle,dict) or any(not isinstance(bundle.get(key),dict) or not {'waiting','congestion'} <= set(bundle[key])
        for key in ('models','reference','uncertainty')):
        raise ModelArtifactError('Model bundle schema is incompatible')
    if any(not callable(getattr(model,'predict',None)) for model in bundle['models'].values()):
        raise ModelArtifactError('Model estimators require a predict method')
    return bundle, metadata


class ModelRegistry:
    def __init__(self, directory):
        self.directory = Path(directory).resolve()

    def exists(self):
        return (self.directory/'active.json').is_file()

    def load(self, version=None):
        try:
            pointer = json.loads((self.directory/'active.json').read_text(encoding='utf-8')) if version is None else None
            version = version or pointer['model_version']
            if not re.fullmatch(r'ml-v1-[a-f0-9]{16}', version):
                raise ModelArtifactError('Invalid model version')
            path = self.directory/version
            digest = pointer['metadata_sha256'] if pointer else hashlib.sha256((path/'metadata.json').read_bytes()).hexdigest()
            meta = json.loads((path/'metadata.json').read_text(encoding='utf-8'))
            if not isinstance(meta,dict) or not isinstance(meta.get('files'),dict):
                raise ModelArtifactError('Invalid model metadata schema')
            signature=[]
            for filename in meta['files']:
                artifact=(path/filename).resolve()
                if not artifact.is_relative_to(path.resolve()):
                    raise ModelArtifactError('Model artifact path is outside the version directory')
                stat=artifact.stat();signature.append((filename,stat.st_size,stat.st_mtime_ns))
            bundle, metadata = _load(str(path), digest, tuple(signature))
            if metadata['model_version'] != version:
                raise ModelArtifactError('Model version mismatch')
            return bundle, metadata
        except ModelArtifactError:
            raise
        except (OSError, KeyError, TypeError, AttributeError, ValueError, EOFError, ImportError) as error:
            raise ModelArtifactError('Model artifacts are missing or invalid; run the training CLI') from error
