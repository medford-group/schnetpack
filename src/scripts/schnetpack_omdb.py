#!/usr/bin/env python
import logging
import os
import torch

import schnetpack as spk
import schnetpack.train.metrics
from schnetpack.datasets import OrganicMaterialsDatabase
from schnetpack.utils.script_utils import (
    setup_run,
    get_model,
    get_representation,
    get_trainer,
    evaluate,
    get_main_parser,
    add_subparsers,
    get_loaders,
    get_statistics,
)


logging.basicConfig(level=os.environ.get("LOGLEVEL", "INFO"))


if __name__ == "__main__":
    # parse arguments
    parser = get_main_parser()
    add_subparsers(
        parser,
        defaults=dict(
            property=OrganicMaterialsDatabase.BandGap,
            features=64,
            patience=6,
            aggregation_mode="mean",
        ),
        choices=dict(property=[OrganicMaterialsDatabase.BandGap]),
    )

    args = parser.parse_args()
    train_args = setup_run(args)

    # set device
    device = torch.device("cuda" if args.cuda else "cpu")

    # define metrics
    metrics = [
        schnetpack.train.metrics.MeanAbsoluteError(
            train_args.property, train_args.property
        ),
        schnetpack.train.metrics.RootMeanSquaredError(
            train_args.property, train_args.property
        ),
    ]

    # build dataset
    logging.info("OMDB will be loaded...")
    omdb = spk.datasets.OrganicMaterialsDatabase(
        args.datapath, args.cutoff, download=True, load_only=[train_args.property]
    )

    # get atomrefs
    atomref = omdb.get_atomrefs(train_args.property)

    # splits the dataset in test, val, train sets
    split_path = os.path.join(args.modelpath, "split.npz")
    train_loader, val_loader, test_loader = get_loaders(
        args, dataset=omdb, split_path=split_path, logging=logging
    )

    if args.mode == "train":
        # get statistics
        logging.info("calculate statistics...")
        mean, stddev = get_statistics(
            split_path, train_loader, train_args, atomref, logging=logging
        )

        # build representation
        representation = get_representation(train_args, train_loader=train_loader)

        # build output module
        if args.model == "schnet":
            output_module = schnetpack.atomistic.output_modules.Atomwise(
                args.features,
                aggregation_mode=args.aggregation_mode,
                mean=mean[args.property],
                stddev=stddev[args.property],
                atomref=atomref[args.property],
                train_embeddings=True,
                property=args.property,
            )
        else:
            raise NotImplementedError

        # build AtomisticModel
        model = get_model(
            representation=representation,
            output_modules=output_module,
            parallelize=args.parallel,
        )

        # run training
        logging.info("training...")
        trainer = get_trainer(args, model, train_loader, val_loader, metrics)
        trainer.train(device, n_epochs=args.n_epochs)
        logging.info("...training done!")

    elif args.mode == "eval":

        # load model
        model = torch.load(os.path.join(args.modelpath, "best_model"))

        # run evaluation
        logging.info("evaluating...")
        with torch.no_grad():
            evaluate(
                args,
                model,
                train_loader,
                val_loader,
                test_loader,
                device,
                metrics=metrics,
            )
        logging.info("... done!")
    else:
        print("Unknown mode:", args.mode)
