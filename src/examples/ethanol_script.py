import os
import logging
from torch.optim import Adam
import schnetpack as spk
import schnetpack.atomistic.model
from schnetpack.train import Trainer, CSVHook, ReduceLROnPlateauHook
from schnetpack.train.metrics import MeanAbsoluteError
from schnetpack.train.metrics import mse_loss


logging.basicConfig(level=os.environ.get("LOGLEVEL", "INFO"))


# basic settings
model_dir = "ethanol_model"  # directory that will be created for storing model
os.makedirs(model_dir)
properties = ["energy", "forces"]  # properties used for training

# data preparation
logging.info("get dataset")
dataset = spk.AtomsData("data/ethanol.db", load_only=properties)
train, val, test = spk.train_test_split(
    data=dataset,
    num_train=1000,
    num_val=100,
    split_file=os.path.join(model_dir, "split.npz"),
)
train_loader = spk.AtomsLoader(train, batch_size=64)
val_loader = spk.AtomsLoader(val, batch_size=64)

# get statistics
atomrefs = dataset.get_atomrefs(properties)
per_atom = dict(energy=True, forces=False)
means, stddevs = train_loader.get_statistics(
    properties, single_atom_ref=atomrefs, get_atomwise_statistics=per_atom
)

# model build
logging.info("build model")
representation = spk.SchNet(n_interactions=6)
output_modules = [
    spk.Atomwise(
        property="energy",
        derivative="forces",
        mean=means["energy"],
        stddev=stddevs["energy"],
        negative_dr=True,
    )
]
model = schnetpack.atomistic.model.AtomisticModel(representation, output_modules)

# build optimizer
optimizer = Adam(params=model.parameters(), lr=1e-4)

# hooks
logging.info("build trainer")
metrics = [MeanAbsoluteError(p, p) for p in properties]
hooks = [CSVHook(log_path=model_dir, metrics=metrics), ReduceLROnPlateauHook(optimizer)]

# trainer
loss = mse_loss(properties)
trainer = Trainer(
    model_dir,
    model=model,
    hooks=hooks,
    loss_fn=loss,
    optimizer=optimizer,
    train_loader=train_loader,
    validation_loader=val_loader,
)

# run training
logging.info("training")
trainer.train(device="cpu", n_epochs=1000)
